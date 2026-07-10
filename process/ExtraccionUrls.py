"""
sync_imagenes_drive_sheets.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Lee una carpeta raíz en Google Drive (con una subcarpeta por
producto), construye las URLs de cada imagen y rellena las
columnas de "imagen principal" e "imágenes adicionales"
directamente en un archivo de GOOGLE SHEETS.

Cada vez que se ejecuta, vuelve a leer TODAS las carpetas de
Drive y reescribe las celdas correspondientes — así detecta
fotos nuevas, reemplazadas o eliminadas automáticamente.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# ════════════════════════════════════════════════════════════════════════════
#  ⚙️  CONFIGURACIÓN — EDITA ÚNICAMENTE ESTE BLOQUE PARA CADA CLIENTE/PROYECTO
# ════════════════════════════════════════════════════════════════════════════
#
#  📄 CÓMO OBTENER EL ARCHIVO "credentials.json" (llave de acceso a Google)
#  ────────────────────────────────────────────────────────────────────────
#  Este script necesita un archivo de credenciales OAuth para poder leer
#  Google Drive y escribir en Google Sheets en nombre del usuario. Se genera
#  UNA SOLA VEZ por cada cuenta/proyecto de Google, siguiendo estos pasos:
#
#   1. Entra a Google Cloud Console:  https://console.cloud.google.com/
#   2. Arriba a la izquierda, crea un proyecto nuevo (o selecciona uno
#      existente) — el nombre no importa, ej. "Sincronizador Productos".
#   3. En el menú lateral, ve a "APIs y servicios" > "Biblioteca".
#      Busca y ACTIVA estas dos APIs (una por una):
#        • Google Drive API
#        • Google Sheets API
#   4. Ve a "APIs y servicios" > "Pantalla de consentimiento OAuth".
#        • Tipo de usuario: "Externo" (a menos que tengas Google Workspace).
#        • Completa nombre de la app, correo de soporte y correo de
#          contacto del desarrollador. Guarda y continúa en cada paso.
#        • En "Usuarios de prueba", agrega el correo de Gmail que va a
#          usarse para autorizar el script (mientras la app no esté
#          publicada, solo esos correos podrán iniciar sesión).
#   5. Ve a "APIs y servicios" > "Credenciales".
#        • Clic en "+ Crear credenciales" > "ID de cliente de OAuth".
#        • Tipo de aplicación: "Aplicación de escritorio".
#        • Ponle un nombre y clic en "Crear".
#   6. Te va a mostrar el ID de cliente creado — clic en el ícono de
#      descarga (⬇) junto a él para bajar el archivo JSON.
#   7. Guarda ese archivo en tu computadora y copia su ruta completa
#      abajo en CREDENTIALS_JSON (usa una "r" antes de las comillas en
#      Windows para que las barras invertidas \ no den error).
#
#  La PRIMERA vez que ejecutes el script, se abrirá el navegador pidiendo
#  que inicies sesión con esa cuenta de Google y aceptes los permisos.
#  Después de eso, se genera automáticamente un "token_sheets.json" en la
#  misma carpeta, y ya no te pedirá iniciar sesión de nuevo (a menos que
#  el token expire o cambies los permisos/SCOPES).
#
# ────────────────────────────────────────────────────────────────────────

# 🔑 Ruta al archivo de credenciales descargado de Google Cloud Console
CREDENTIALS_JSON = r"D:\Projects\2026\Development\Python\Keys\SincronizaHEXIBO.json"

# 📊 ID de la hoja de Google Sheets a actualizar
#     (se obtiene de la URL: docs.google.com/spreadsheets/d/ESTE_ES_EL_ID/edit)
SPREADSHEET_ID = "1e54To2EhPiPk92Wkh1wcn5lAxXaxlMf2bDPfazbFOhg"

# 🏷️  Nombre exacto de la pestaña dentro del Google Sheet
SHEET_NAME = "Productos"

# 📁 ID de la carpeta raíz en Google Drive que contiene una subcarpeta
#     por cada producto (se obtiene de la URL de la carpeta en Drive)
CARPETA_RAIZ_DRIVE_ID = "1sgW_1po2tOsgjT9Q-7TUgHebYBq9hN4E"

# 🧩 Nombres exactos de las columnas en la primera fila del Google Sheet
ID_COLUMN_NAME        = "id"
IMAGEN_COLUMN_NAME    = "imagen"
IMAGENES_COLUMN_NAME  = "imagenes"

# ════════════════════════════════════════════════════════════════════════════
#  ⚠️  A PARTIR DE AQUÍ NO ES NECESARIO EDITAR NADA — LÓGICA DEL PROGRAMA
# ════════════════════════════════════════════════════════════════════════════

import os
import sys
import time
import re
import json

def instalar_dependencias():
    import subprocess
    print("📦 Instalando dependencias...")
    subprocess.check_call([sys.executable, "-m", "pip", "install",
        "google-api-python-client", "google-auth-httplib2",
        "google-auth-oauthlib", "-q"])

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    instalar_dependencias()
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

# Scopes de lectura para Drive y escritura para Spreadsheets
# (se agrega userinfo.email SOLO para poder mostrarte con qué cuenta de
#  Google quedó autenticado el script — así podés confirmar que es la
#  cuenta correcta, la que tiene permiso de Editor sobre el Sheet)
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
TOKEN_FILE = os.path.join(os.path.dirname(CREDENTIALS_JSON), "token_sheets.json")


def autenticar():
    """Autentica con Google Drive y Sheets. Abre el navegador la primera vez."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        # Si el token guardado no tiene TODOS los scopes que necesitamos hoy
        # (por ejemplo, viene de una versión anterior del script), lo descartamos
        # para forzar un nuevo login con los permisos correctos.
        if creds and creds.scopes and not set(SCOPES).issubset(set(creds.scopes)):
            print("   ⚠️ El token guardado no tiene los permisos necesarios (scopes desactualizados). Se pedirá iniciar sesión de nuevo.")
            os.remove(TOKEN_FILE)
            creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"   ⚠️ Error refrescando token: {e}")
                os.remove(TOKEN_FILE)
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_JSON, SCOPES)
            # prompt='consent select_account' fuerza TANTO el selector de
            # cuenta COMO la pantalla completa de permisos, evitando que
            # Google reutilice silenciosamente un consentimiento viejo con
            # permisos más restringidos (ej. solo lectura en vez de lectura+escritura).
            creds = flow.run_local_server(port=0, prompt='consent select_account')
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
            
    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)

    # 🔎 Averiguamos con qué cuenta de Google quedó autenticado el script.
    # Esto es clave para diagnosticar errores 403 "the caller does not have
    # permission": si esta cuenta no es la que tiene acceso de Editor al
    # Sheet, TODAS las escrituras van a fallar sin importar el token/scopes.
    email_autenticado = None
    try:
        oauth2_service = build("oauth2", "v2", credentials=creds)
        userinfo = oauth2_service.userinfo().get().execute()
        email_autenticado = userinfo.get("email")
    except Exception as e:
        print(f"   ⚠️ No se pudo determinar la cuenta autenticada: {e}")

    return drive_service, sheets_service, email_autenticado


def listar_todas_las_carpetas(service, parent_id):
    carpetas = {}
    page_token = None
    while True:
        try:
            resp = service.files().list(
                q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
        except HttpError as e:
            print(f"   ❌ Error de API Drive: {e}")
            break
            
        for f in resp.get("files", []):
            carpetas[f["name"].strip()] = f["id"]
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return carpetas


def listar_imagenes(service, folder_id):
    MIME_IMAGENES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff", "image/jpg")
    mime_query = " or ".join([f"mimeType='{m}'" for m in MIME_IMAGENES])
    imagenes = []
    page_token = None
    
    while True:
        try:
            resp = service.files().list(
                q=f"'{folder_id}' in parents and ({mime_query}) and trashed=false",
                fields="nextPageToken, files(id, name)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
        except HttpError as e:
            print(f"   ⚠️ Error listando imágenes: {e}")
            break
            
        for f in resp.get("files", []):
            imagenes.append((f["name"].strip(), f["id"]))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    
    imagenes.sort(key=lambda x: natural_sort_key(x[0]))
    return imagenes


def natural_sort_key(texto):
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', texto)]


def url_directa(file_id):
    return f"https://drive.google.com/uc?export=view&id={file_id}"


def col_idx_to_letter(col_idx):
    """Convierte número de columna (base 1) a letras estilo Excel (ej: 1 -> A, 28 -> AB)"""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def normalizar(texto):
    """Limpia textos quitando tildes, espacios y pasando a minúsculas."""
    texto = str(texto).strip().lower()
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    return texto


def main():
    print("\n" + "="*70)
    print("   🔄  Sincronización de Imágenes: Google Drive → Google Sheets")
    print("="*70 + "\n")

    if not os.path.exists(CREDENTIALS_JSON):
        print(f"❌ No se encontró credentials.json")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    # 1. Autenticar
    print("🔐 Autenticando con Google Workspace...")
    try:
        drive_service, sheets_service, email_autenticado = autenticar()
        if email_autenticado:
            print(f"   ✅ Autenticado en Drive y Sheets como: {email_autenticado}")
            print(f"      👉 Verificá que ESTA cuenta tenga acceso de EDITOR")
            print(f"         al Google Sheet (no solo Lector/Comentador).\n")
        else:
            print("   ✅ Autenticado en Drive y Sheets\n")
    except Exception as e:
        print(f"   ❌ Error de autenticación: {e}")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    # 2. Leer carpetas de productos en Drive
    print(f"📁 Leyendo carpetas en Drive (ID: {CARPETA_RAIZ_DRIVE_ID})...")
    carpetas = listar_todas_las_carpetas(drive_service, CARPETA_RAIZ_DRIVE_ID)
    print(f"   ✅ {len(carpetas)} carpetas encontradas\n")

    if not carpetas:
        print("❌ No se encontraron subcarpetas. Verificá el CARPETA_RAIZ_DRIVE_ID.")
        print("   💡 Si la carpeta está dentro de una Unidad Compartida (Shared Drive),")
        print("      confirmá que la cuenta con la que iniciaste sesión tiene acceso a esa unidad.")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    # 3. Leer datos desde Google Sheets
    print(f"📊 Leyendo Google Sheet (ID: {SPREADSHEET_ID})...")
    try:
        rango_lectura = f"'{SHEET_NAME}'!A1:Z"
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=rango_lectura
        ).execute()
        rows = result.get('values', [])
    except HttpError as e:
        print(f"   ❌ Error leyendo la hoja de Google Sheets: {e}")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    if not rows:
        print("❌ La hoja de cálculo está vacía o la pestaña no existe.")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    # 4. Detectar columnas usando normalización (Tolera mayúsculas/minúsculas y tildes)
    headers_normalizados = [normalizar(h) for h in rows[0]]
    
    try:
        col_id_idx = headers_normalizados.index(normalizar(ID_COLUMN_NAME))
        col_img_idx = headers_normalizados.index(normalizar(IMAGEN_COLUMN_NAME))
        col_imgs_idx = headers_normalizados.index(normalizar(IMAGENES_COLUMN_NAME))
    except ValueError as e:
        print(f"❌ No se pudo encontrar una de las columnas necesarias en la primera fila.")
        print(f"Buscados: '{ID_COLUMN_NAME}', '{IMAGEN_COLUMN_NAME}', '{IMAGENES_COLUMN_NAME}'")
        print(f"Encabezados actuales detectados en la hoja: {rows[0]}")
        input("\nPresioná Enter para cerrar...")
        sys.exit(1)

    print(f"   📍 Columnas detectadas:")
    print(f"      → ID: columna {col_id_idx + 1} ('{rows[0][col_id_idx]}')")
    print(f"      → Imagen: columna {col_img_idx + 1} ('{rows[0][col_img_idx]}')")
    print(f"      → Imágenes: columna {col_imgs_idx + 1} ('{rows[0][col_imgs_idx]}')\n")

    col_img_letter = col_idx_to_letter(col_img_idx + 1)
    col_imgs_letter = col_idx_to_letter(col_imgs_idx + 1)

    # 5. Recorrer filas y preparar lote de actualización
    actualizados = 0
    sin_carpeta  = 0
    sin_imagenes = 0
    errores      = 0
    ejemplos_sin_carpeta = []

    total_filas = len(rows) - 1
    print(f"🔄 Procesando e inspeccionando {total_filas} productos...")
    inicio = time.time()
    
    data_updates = []

    for pos, (idx, row) in enumerate(enumerate(rows[1:], start=2), start=1):
        # Contador de progreso en vivo — se reescribe en la misma línea (\r)
        # para no inundar la consola. flush=True fuerza que se muestre de
        # inmediato aunque el editor/terminal esté bufferizando la salida.
        print(f"\r   ⏳ Progreso: {pos}/{total_filas} productos revisados "
              f"({actualizados} actualizados, {errores} errores)   ",
              end="", flush=True)

        if len(row) <= col_id_idx:
            continue
            
        producto_id = str(row[col_id_idx]).strip()
        if not producto_id or producto_id == "None":
            continue

        folder_id = carpetas.get(producto_id)
        if not folder_id:
            sin_carpeta += 1
            if len(ejemplos_sin_carpeta) < 10:
                ejemplos_sin_carpeta.append(producto_id)
            continue

        # [MODIFICACIÓN CLAVE]: Se removió la condición de "skip/saltar" si la celda ya tenía URL.
        # Ahora siempre lee la carpeta de Drive para detectar imágenes actualizadas o nuevas.
        try:
            imagenes = listar_imagenes(drive_service, folder_id)
        except Exception as e:
            print(f"\n   ⚠️ Error en carpeta {producto_id}: {e}")
            errores += 1
            continue
            
        if not imagenes:
            sin_imagenes += 1
            continue

        url_principal = url_directa(imagenes[0][1])
        if len(imagenes) > 1:
            resto_urls = " | ".join([url_directa(img[1]) for img in imagenes[1:]])
        else:
            resto_urls = url_principal

        # Agrupar datos en el lote de reescritura masiva
        data_updates.append({
            'range': f"'{SHEET_NAME}'!{col_img_letter}{idx}",
            'values': [[url_principal]]
        })
        data_updates.append({
            'range': f"'{SHEET_NAME}'!{col_imgs_letter}{idx}",
            'values': [[resto_urls]]
        })

        actualizados += 1

    # Línea final del contador, con salto de línea para no pisar el resumen
    print(f"\r   ✅ Progreso: {total_filas}/{total_filas} productos revisados "
          f"({actualizados} actualizados, {errores} errores)          ")

    # 6. Guardar en Google Sheets en LOTES (más resiliente a cortes de red)
    elapsed_total = time.time() - inicio
    if data_updates:
        TAMANO_LOTE = 400  # celdas por solicitud (200 productos aprox., ya que cada uno usa 2 celdas)
        MAX_REINTENTOS = 3

        lotes = [data_updates[i:i + TAMANO_LOTE] for i in range(0, len(data_updates), TAMANO_LOTE)]
        total_lotes = len(lotes)
        print(f"\n💾 Subiendo {len(data_updates)//2} filas sincronizadas a Google Sheets "
              f"(en {total_lotes} lotes de hasta {TAMANO_LOTE//2} productos cada uno)...")

        lotes_fallidos = []
        for i, lote in enumerate(lotes, start=1):
            body = {'valueInputOption': 'USER_ENTERED', 'data': lote}
            exito_lote = False

            # Rango de filas que cubre este lote (útil para detectar si el
            # 403 viene de un "rango protegido" del Sheet que arranca en
            # cierta fila — comparalo con Datos > Hojas y rangos protegidos)
            filas_del_lote = sorted({
                int(re.search(r'!\D+(\d+)$', d['range']).group(1))
                for d in lote if re.search(r'!\D+(\d+)$', d['range'])
            })
            rango_filas_txt = (f"filas {filas_del_lote[0]}–{filas_del_lote[-1]}"
                                if filas_del_lote else "filas desconocidas")

            for intento in range(1, MAX_REINTENTOS + 1):
                try:
                    sheets_service.spreadsheets().values().batchUpdate(
                        spreadsheetId=SPREADSHEET_ID, body=body
                    ).execute()
                    exito_lote = True
                    break
                except (HttpError, ConnectionAbortedError, ConnectionError, OSError) as e:
                    detalle = str(e)
                    if isinstance(e, HttpError):
                        try:
                            err_json = json.loads(e.content.decode("utf-8"))
                            err_info = err_json.get("error", {})
                            status = err_info.get("status")
                            reason = None
                            for d in err_info.get("errors", []):
                                reason = d.get("reason")
                                break
                            detalle = (f"HTTP {e.resp.status} | status={status} "
                                       f"reason={reason} | {err_info.get('message')}")
                        except Exception:
                            pass
                    print(f"\r   ⚠️ Lote {i}/{total_lotes} ({rango_filas_txt}) falló "
                          f"(intento {intento}/{MAX_REINTENTOS}): {detalle}")
                    if intento < MAX_REINTENTOS:
                        time.sleep(2 * intento)  # espera creciente antes de reintentar

            if exito_lote:
                print(f"\r   ✅ Lote {i}/{total_lotes} guardado correctamente.          ", end="", flush=True)
            else:
                lotes_fallidos.append(i)
                print(f"\n   ❌ Lote {i}/{total_lotes} ({rango_filas_txt}) falló tras "
                      f"{MAX_REINTENTOS} intentos — se omitió, continuando con el resto.")

        print()
        if lotes_fallidos:
            print(f"   ⚠️ {len(lotes_fallidos)} de {total_lotes} lotes NO se pudieron guardar "
                  f"(números: {lotes_fallidos}). Corré el script de nuevo para reintentar solo esas filas.")
        else:
            print("   ✅ Google Sheets actualizado con éxito (todos los lotes).")
    else:
        print("\nℹ️ No se encontraron filas aptas para actualización.")

    # 7. Resumen final
    print(f"\n{'='*70}")
    print(f"   ✅ COMPLETADO en {elapsed_total:.1f} segundos")
    print(f"{'='*70}")
    print(f"   🔄 Productos sincronizados / actualizados : {actualizados}")
    print(f"   📁 Sin carpeta en Drive                    : {sin_carpeta}")
    print(f"   🖼️  Carpeta vacía (sin imágenes)            : {sin_imagenes}")
    print(f"   ⚠️  Errores durante el proceso              : {errores}")
    print(f"   📊 Total filas de datos evaluadas          : {total_filas}")
    print(f"{'='*70}\n")

    if ejemplos_sin_carpeta:
        print("   🔎 Ejemplos de IDs del Sheet sin carpeta coincidente en Drive:")
        for eid in ejemplos_sin_carpeta:
            print(f"      - '{eid}'")
        print("   🔎 Ejemplos de nombres de carpeta encontrados en Drive:")
        for nombre in list(carpetas.keys())[:10]:
            print(f"      - '{nombre}'")
        print("   👉 Compará ambas listas: si los IDs y los nombres de carpeta no coinciden")
        print("      exactamente (mayúsculas, espacios, tildes, ceros a la izquierda, etc.),")
        print("      por eso no se están rellenando esas filas.\n")
    
    cobertura = (actualizados) / total_filas * 100 if total_filas > 0 else 0
    print(f"   📈 Cobertura de imágenes actual: {cobertura:.1f}%")
    print(f"\n{'='*70}\n")
    input("Presioná Enter para cerrar...")


if __name__ == "__main__":
    main()