"""
DescargaImagenesEkiipa.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Descarga todas las imágenes de un catálogo WooCommerce
(categorías → productos → imágenes), organizándolas en
carpetas por SKU.

Soporta JPG, PNG, WEBP, AVIF y GIF. La extensión del archivo
se detecta primero por la URL y, si no es concluyente, por el
Content-Type real de la respuesta — así nunca se guarda una
imagen webp/avif con extensión .png (o viceversa).

Pensado para poder reutilizarse en distintos sitios/clientes:
toda la configuración específica del sitio vive en el bloque
CONFIG de más abajo. Para un nuevo cliente, normalmente solo
hace falta cambiar BASE_URL, BASE_DIR y (si el tema no es un
WooCommerce estándar) los selectores CSS.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import glob
import time
import random
import requests
from playwright.sync_api import sync_playwright
from tqdm import tqdm

# ── CONFIGURACIÓN (todo lo que cambia entre sitios/clientes va acá) ───────────
CONFIG = {
    # Carpeta local donde se guardan las imágenes descargadas
    "BASE_DIR": r"D:\ekiipa",

    # URL de la tienda a scrapear
    "BASE_URL": "https://ekiipa.com/tienda/",

    # User-Agent que se envía tanto al navegador como a las descargas directas
    "USER_AGENT": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),

    # Selectores CSS (funcionan tal cual con la mayoría de temas WooCommerce)
    "SELECTOR_CATEGORIAS": ".cat-item a",
    "SELECTOR_PRODUCTOS": ".product-title a",
    "SELECTOR_SKU": ".sku",
    "SELECTOR_IMAGENES": ".woocommerce-product-gallery__image a, .woocommerce-product-gallery .wp-post-image",

    # Atributos donde puede venir la URL real de la imagen, en orden de prioridad.
    # Muchos temas usan "lazy loading" y ponen la URL real en data-src en vez de src.
    "ATRIBUTOS_IMAGEN": ["href", "src", "data-src", "data-lazy-src", "data-srcset"],

    # Extensiones de imagen válidas
    "EXTENSIONES_VALIDAS": [".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"],

    # Pausa aleatoria (segundos) entre productos, para evitar bloqueos
    "PAUSA_MIN": 2,
    "PAUSA_MAX": 4,

    # Timeout de las descargas de imagen (segundos)
    "REQUEST_TIMEOUT": 15,

    # Reintentos por imagen si falla la descarga
    "MAX_REINTENTOS": 2,

    # False = ves el navegador mientras corre (útil para depurar).
    # True = navegador invisible (más rápido, ideal para dejarlo corriendo solo).
    "HEADLESS": False,
}
# ────────────────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": CONFIG["USER_AGENT"]}

# Mapeo de Content-Type real -> extensión, para cuando la URL no trae extensión
# clara (muy común en imágenes servidas por CDNs o plugins de optimización).
CONTENT_TYPE_A_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
    "image/gif": ".gif",
}


def obtener_extension_de_url(url):
    """Devuelve la extensión si la URL trae una válida y reconocible, si no None."""
    ruta = url.split("?")[0].split("#")[0]
    ext = os.path.splitext(ruta)[1].lower()
    return ext if ext in CONFIG["EXTENSIONES_VALIDAS"] else None


def ya_descargada(sku_dir, nombre_base):
    """Revisa si ya existe un archivo para este índice, sin importar la extensión."""
    return len(glob.glob(os.path.join(sku_dir, f"{nombre_base}.*"))) > 0


def descargar_imagen(url, sku_dir, nombre_base):
    """
    Descarga una imagen intentando varias veces. Determina la extensión real
    por la URL o, si no es concluyente, por el Content-Type de la respuesta.
    Devuelve True si se guardó correctamente.
    """
    ext_url = obtener_extension_de_url(url)

    for intento in range(1, CONFIG["MAX_REINTENTOS"] + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=CONFIG["REQUEST_TIMEOUT"])
            if resp.status_code != 200:
                continue

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()

            # Si el Content-Type no es una imagen (ej. una página de error/login
            # devuelta con status 200), no la guardamos.
            if not content_type.startswith("image/"):
                tqdm.write(f"   ⚠️ Respuesta no es una imagen ({content_type}) en {url}")
                return False

            ext = ext_url or CONTENT_TYPE_A_EXT.get(content_type, ".jpg")
            file_path = os.path.join(sku_dir, f"{nombre_base}{ext}")

            with open(file_path, "wb") as f:
                f.write(resp.content)
            return True

        except Exception as e:
            if intento == CONFIG["MAX_REINTENTOS"]:
                tqdm.write(f"   ❌ Error descargando {url}: {e}")
            else:
                time.sleep(1)

    return False


def obtener_url_imagen(img_element):
    """
    Prueba varios atributos (src, data-src, etc.) hasta encontrar una URL usable.
    Ignora los que sean "data:" URIs (placeholders base64 típicos de lazy loading,
    como data:image/svg+xml,... — no son URLs descargables).
    """
    for attr in CONFIG["ATRIBUTOS_IMAGEN"]:
        valor = img_element.get_attribute(attr)
        if valor and not valor.strip().lower().startswith("data:"):
            # srcset trae varias URLs con tamaños; nos quedamos con la primera
            return valor.split(",")[0].strip().split(" ")[0]
    return None


def limpiar_sku(raw_sku):
    """Limpia caracteres inválidos para nombres de carpeta en Windows."""
    return raw_sku.replace("/", "-").replace("\\", "-").replace(":", "-").strip()


def run_scraper():
    base_dir = CONFIG["BASE_DIR"]
    os.makedirs(base_dir, exist_ok=True)

    total_descargadas = 0
    total_omitidas = 0
    total_fallidas = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=CONFIG["HEADLESS"])
        page = browser.new_page()
        page.goto(CONFIG["BASE_URL"])

        # 1. Obtener enlaces de categorías
        cat_links = list(set(page.evaluate(
            f"() => Array.from(document.querySelectorAll('{CONFIG['SELECTOR_CATEGORIAS']}')).map(a => a.href)"
        )))

        for cat_url in tqdm(cat_links, desc="Progreso Total Categorías"):
            try:
                page.goto(cat_url)
                # 2. Obtener enlaces de productos
                prod_links = list(set(page.evaluate(
                    f"() => Array.from(document.querySelectorAll('{CONFIG['SELECTOR_PRODUCTOS']}')).map(a => a.href)"
                )))

                for p_url in tqdm(prod_links, desc=f"Productos en {cat_url.split('/')[-2][:10]}", leave=False):
                    page.goto(p_url)
                    time.sleep(random.uniform(CONFIG["PAUSA_MIN"], CONFIG["PAUSA_MAX"]))

                    # Identificar SKU para crear carpeta
                    sku_el = page.query_selector(CONFIG["SELECTOR_SKU"])
                    raw_sku = sku_el.inner_text().strip() if sku_el else "sin_sku"
                    sku = limpiar_sku(raw_sku)

                    sku_dir = os.path.join(base_dir, sku)
                    os.makedirs(sku_dir, exist_ok=True)

                    # 3. Obtener imágenes
                    imgs = page.query_selector_all(CONFIG["SELECTOR_IMAGENES"])
                    for i, img in enumerate(imgs):
                        img_url = obtener_url_imagen(img)
                        if not img_url:
                            continue

                        nombre_base = f"{sku}_{i}"

                        # Evita re-descargar si ya existe con cualquier extensión
                        if ya_descargada(sku_dir, nombre_base):
                            total_omitidas += 1
                            continue

                        if descargar_imagen(img_url, sku_dir, nombre_base):
                            total_descargadas += 1
                        else:
                            total_fallidas += 1

            except Exception as e:
                tqdm.write(f"Error en categoria {cat_url}: {e}")

        browser.close()

    print(f"\n{'='*60}")
    print(f"🚀 Proceso terminado. Imágenes guardadas en: {base_dir}")
    print(f"   ✅ Descargadas : {total_descargadas}")
    print(f"   ⏭️  Ya existían : {total_omitidas}")
    print(f"   ❌ Fallidas     : {total_fallidas}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run_scraper()