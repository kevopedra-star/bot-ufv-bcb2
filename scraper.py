import os
import sys
import time
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Error: Faltan las llaves de Supabase en las variables de entorno.")
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

# Evaluar si se ejecuta en modo histórico
MODO_HISTORICO = os.environ.get("MODO_HISTORICO", "false").lower() == "true"

if MODO_HISTORICO:
    fecha_ini = datetime(2026, 1, 1)
    fecha_fin = datetime(2026, 9, 25)
    print(">>> MODO HISTORICO ACTIVADO: 01/01/2026 al 25/09/2026 <<<")
else:
    fecha_fin = datetime.now()
    fecha_ini = fecha_fin - timedelta(days=5)
    print(f">>> MODO DIARIO: {fecha_ini.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')} <<<")

options = webdriver.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1920,1080")
options.add_argument("--log-level=3")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
wait = WebDriverWait(driver, 25)

try:
    url = "https://www.bcb.gob.bo/?q=servicios/ufv/datos_estadisticos"
    driver.get(url)

    # Seleccionar vista de períodos
    wait.until(EC.presence_of_element_located((By.ID, "combos1_5")))
    driver.execute_script("""
        var sel = document.getElementById('combos1_5');
        sel.value = '4';
        if (typeof nvjs_indiLoad === 'function') {
            nvjs_indiLoad(1, 5);
        }
    """)
    time.sleep(3)

    # Cambiar al iframe
    iframe = wait.until(EC.presence_of_element_located((By.NAME, "indiframe")))
    driver.switch_to.frame(iframe)

    # Esperar los 6 desplegables de fecha
    wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "select")) >= 6)
    selects = driver.find_elements(By.TAG_NAME, "select")

    Select(selects[0]).select_by_visible_text(str(fecha_ini.day))
    Select(selects[1]).select_by_visible_text(MESES_NOMBRE[fecha_ini.month])
    Select(selects[2]).select_by_visible_text(str(fecha_ini.year))

    Select(selects[3]).select_by_visible_text(str(fecha_fin.day))
    Select(selects[4]).select_by_visible_text(MESES_NOMBRE[fecha_fin.month])
    Select(selects[5]).select_by_visible_text(str(fecha_fin.year))

    # Clic al botón Ver
    btn_ver = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@value='Ver' or @type='submit']")))
    driver.execute_script("arguments[0].click();", btn_ver)

    time.sleep(3)
    tabla = wait.until(EC.presence_of_element_located((By.XPATH, "//table[contains(., 'Valor de la UFV')]")))
    filas = tabla.find_elements(By.TAG_NAME, "tr")

    datos_a_insertar = []

    for fila in filas:
        columnas = fila.find_elements(By.TAG_NAME, "td")
        if len(columnas) >= 3:
            nro_txt = columnas[0].text.strip()
            fecha_txt = columnas[1].text.strip()
            valor_txt = columnas[2].text.strip()

            if nro_txt.isdigit():
                partes = fecha_txt.split(" de ")
                if len(partes) == 3:
                    dia = int(partes[0])
                    mes = MESES_NUMERO[partes[1].lower()]
                    anio = int(partes[2])
                    fecha_iso = f"{anio:04d}-{mes:02d}-{dia:02d}"
                    valor_limpio = float(valor_txt.replace(",", "."))

                    datos_a_insertar.append({
                        "nro": int(nro_txt),
                        "fecha": fecha_iso,
                        "valor_ufv": valor_limpio
                    })

    print(f"Total registros extraidos: {len(datos_a_insertar)}")

    # Guardar en Supabase usando upsert para evitar registros duplicados
    if datos_a_insertar:
        supabase.table("ufv_datos").upsert(datos_a_insertar, on_conflict="fecha").execute()
        print("Datos insertados o actualizados en Supabase con éxito.")

finally:
    driver.quit()
