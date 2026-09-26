import os
import sys
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Gwall: Mae SUPABASE_URL neu SUPABASE_KEY ar goll.")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

MESES_NOMBRE = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

MESES_NUMERO = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

modo_env = os.environ.get("MODO_HISTORICO", "false").strip().lower()
MODO_HISTORICO = modo_env in ["true", "1", "t", "yes"]

if MODO_HISTORICO:
    fecha_ini = datetime(2026, 1, 1)
    fecha_fin = datetime(2026, 9, 25)
    print(f"Buscando rango: 01/01/2026 al 25/09/2026 (Modo silencioso)...\n")
else:
    fecha_fin = datetime.now()
    fecha_ini = fecha_fin - timedelta(days=5)
    print(f"Buscando rango: {fecha_ini.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')} (Modo silencioso)...\n")

options = webdriver.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 30)

try:
    url = "https://www.bcb.gob.bo/?q=servicios/ufv/datos_estadisticos"
    driver.get(url)

    wait.until(EC.presence_of_element_located((By.ID, "combos1_5")))
    driver.execute_script("""
        var sel = document.getElementById('combos1_5');
        sel.value = '4';
        if (typeof nvjs_indiLoad === 'function') {
            nvjs_indiLoad(1, 5);
        }
    """)
    time.sleep(4)

    iframe = wait.until(EC.presence_of_element_located((By.NAME, "indiframe")))
    driver.switch_to.frame(iframe)

    wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "select")) >= 6)
    selects = driver.find_elements(By.TAG_NAME, "select")

    def asignar_select(sel_elem, valor_buscado):
        driver.execute_script("""
            var sel = arguments[0];
            var val = arguments[1].toString().trim().toLowerCase();
            for (var i = 0; i < sel.options.length; i++) {
                if (sel.options[i].text.trim().toLowerCase() === val || sel.options[i].value.trim().toLowerCase() === val) {
                    sel.selectedIndex = i;
                    sel.dispatchEvent(new Event('change', { bubbles: true }));
                    break;
                }
            }
        """, sel_elem, str(valor_buscado))

    asignar_select(selects[0], fecha_ini.day)
    asignar_select(selects[1], MESES_NOMBRE[fecha_ini.month])
    asignar_select(selects[2], fecha_ini.year)

    asignar_select(selects[3], fecha_fin.day)
    asignar_select(selects[4], MESES_NOMBRE[fecha_fin.month])
    asignar_select(selects[5], fecha_fin.year)

    time.sleep(1)

    btn_ver = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@value='Ver' or @type='submit']")))
    driver.execute_script("arguments[0].click();", btn_ver)

    wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(., 'Valor de la UFV')]//td")))
    time.sleep(2)

    filas = driver.find_elements(By.XPATH, "//table[contains(., 'Valor de la UFV')]//tr")
    datos_a_insertar = []

    # Arddangos y penawdau tabl[cite: 11]
    print(f"{'Nro.':<6} | {'Fecha':<26} | {'Valor UFV':<10}")
    print("-" * 50)

    for fila in filas:
        columnas = fila.find_elements(By.TAG_NAME, "td")
        if len(columnas) >= 3:
            nro_txt = columnas[0].text.strip()
            fecha_txt = columnas[1].text.strip()
            valor_txt = columnas[2].text.strip()

            if nro_txt.isdigit():
                # Arddangos y rhesi yn union fel yn y ddelwedd[cite: 11]
                print(f"{nro_txt:<6} | {fecha_txt:<26} | {valor_txt:<10}")

                partes = fecha_txt.split(" de ")
                if len(partes) == 3:
                    dia = int(partes[0])
                    mes = MESES_NUMERO.get(partes[1].lower(), 0)
                    anio = int(partes[2])

                    if mes > 0:
                        fecha_iso = f"{anio:04d}-{mes:02d}-{dia:02d}"
                        valor_limpio = float(valor_txt.replace(".", "").replace(",", "."))

                        datos_a_insertar.append({
                            "nro": int(nro_txt),
                            "fecha": fecha_iso,
                            "valor_ufv": valor_limpio
                        })

    print("-" * 50)
    print(f"\nCyfanswm cofnodion a gasglwyd: {len(datos_a_insertar)}")

    if datos_a_insertar:
        batch_size = 100
        for i in range(0, len(datos_a_insertar), batch_size):
            lote = datos_a_insertar[i:i + batch_size]
            supabase.table("ufv_datos").upsert(lote, on_conflict="fecha").execute()
        print("Data wedi'i uwchlwytho'n llwyddiannus i Supabase!")
    else:
        print("Ni ddarganfuwyd unrhyw ddata yn y tabl.")

finally:
    driver.quit()
