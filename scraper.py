import os
import sys
import re
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
    print("Error: SUPABASE_URL o SUPABASE_KEY no configuradas en GitHub Secrets.")
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

# 1. Verificar si la base de datos está vacía; si no tiene registros, forzar histórico
modo_env = str(os.environ.get("MODO_HISTORICO", "")).strip().lower()
es_historico_manual = modo_env in ["true", "1", "yes", "si"]

datos_existentes = supabase.table("ufv_datos").select("id").limit(1).execute()
base_datos_vacia = len(datos_existentes.data) == 0

if es_historico_manual or base_datos_vacia:
    fecha_ini = datetime(2026, 1, 1)
    fecha_fin = datetime(2026, 9, 25)
    print(">>> EJECUTANDO CARGA HISTÓRICA: 01/01/2026 al 25/09/2026 <<<\n")
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

    # Cargar vista de períodos
    wait.until(EC.presence_of_element_located((By.ID, "combos1_5")))
    driver.execute_script("""
        var sel = document.getElementById('combos1_5');
        sel.value = '4';
        if (typeof nvjs_indiLoad === 'function') {
            nvjs_indiLoad(1, 5);
        }
    """)
    time.sleep(4)

    # Pasar al iframe
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

    # Fecha inicial
    asignar_select(selects[0], fecha_ini.day)
    asignar_select(selects[1], MESES_NOMBRE[fecha_ini.month])
    asignar_select(selects[2], fecha_ini.year)

    # Fecha final
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

    print(f"{'Nro.':<6} | {'Fecha':<26} | {'Valor UFV':<10}")
    print("-" * 50)

    for fila in filas:
        columnas = fila.find_elements(By.TAG_NAME, "td")
        if len(columnas) >= 3:
            nro_txt = columnas[0].text.strip()
            fecha_txt = columnas[1].text.strip()
            valor_txt = columnas[2].text.strip()

            if nro_txt.isdigit():
                print(f"{nro_txt:<6} | {fecha_txt:<26} | {valor_txt:<10}")

                # Parseo robusto de fechas como: "21 de Septiembre 2026"
                match = re.search(r"(\d{1,2})\s+de\s+([A-Za-z]+)\s+(\d{4})", fecha_txt, re.IGNORECASE)
                if match:
                    dia = int(match.group(1))
                    mes_nombre = match.group(2).lower()
                    anio = int(match.group(3))
                    mes = MESES_NUMERO.get(mes_nombre, 0)

                    if mes > 0:
                        fecha_iso = f"{anio:04d}-{mes:02d}-{dia:02d}"
                        # Eliminar posibles puntos de miles y sustituir coma por punto
                        val_num = valor_txt.replace(".", "").replace(",", ".")
                        valor_limpio = float(val_num)

                        datos_a_insertar.append({
                            "nro": int(nro_txt),
                            "fecha": fecha_iso,
                            "valor_ufv": valor_limpio
                        })

    print("-" * 50)
    print(f"\nTotal registros preparados para guardar: {len(datos_a_insertar)}")

    if datos_a_insertar:
        # Insertar en lotes de 100 registros con upsert
        batch_size = 100
        for i in range(0, len(datos_a_insertar), batch_size):
            lote = datos_a_insertar[i:i + batch_size]
            supabase.table("ufv_datos").upsert(lote, on_conflict="fecha").execute()
        print("¡Sincronización con Supabase completada con éxito!")
    else:
        print("Atención: No se procesaron filas de datos.")

finally:
    driver.quit()
