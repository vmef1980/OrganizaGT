import requests
from bs4 import BeautifulSoup

url = "https://kossino.com/product/refresquera-simple-de-3-5l/"
response = requests.get(url)
soup = BeautifulSoup(response.text, "html.parser")

# Buscar enlaces dentro de la galería
gallery = soup.find("div", class_="woocommerce-product-gallery")
if gallery:
    links = gallery.find_all("a")
    for a in links:
        href = a.get("href")
        if href and "wp-content/uploads" in href:
            print(href)
else:
    print("No se encontró la galería en el HTML estático.")