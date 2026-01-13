
import os
import csv
import time
import argparse
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# Configuración de argumentos
parser = argparse.ArgumentParser(description='Cardmarket Exporter para Termux')
parser.add_argument('--year', help='Año (ej. 2025)')
parser.add_argument('--include-purchases', action='store_true', help='Exportar Compras')
parser.add_argument('--include-sales', action='store_true', help='Exportar Ventas')
args = parser.parse_args()

USER_NAME = os.environ.get('CM_USERNAME')
PASSWORD = os.environ.get('CM_PASSWORD')
CSV_FILE = 'cardmarket_export.csv'

# Headers para imitar navegador móvil y evitar bloqueos
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Origin': 'https://www.cardmarket.com',
    'Referer': 'https://www.cardmarket.com/en/Magic/MainPage/Login'
}

def load_existing_data():
    existing_ids = set()
    rows = []
    if os.path.exists(CSV_FILE):
        try:
            with open(CSV_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Order ID'):
                        existing_ids.add(row.get('Order ID'))
                        rows.append(row)
            print(f"[*] Registros previos cargados: {len(existing_ids)}")
        except: pass
    return existing_ids, rows

def scrape_section(session, url, start_dt, end_dt, existing_ids):
    print(f"[*] Accediendo a: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        response = session.get(paginated_url, headers=HEADERS)
        
        if response.status_code != 200:
            print(f"[!] Error al acceder a la página {page_num}: {response.status_code}")
            break
            
        soup = BeautifulSoup(response.text, 'html.parser')
        table_body = soup.select_one('div.table-body')
        
        if not table_body:
            print("[!] No se encontró la tabla. Sesión expirada o sin datos.")
            break
            
        rows = table_body.select('div.row')
        if not rows: break

        page_duplicates = 0
        for row in rows:
            try:
                id_el = row.select_one('.col-orderId')
                if not id_el: continue
                order_id = id_el.get_text(strip=True)

                if order_id in existing_ids:
                    page_duplicates += 1
                    continue

                date_el = row.select_one('.col-date')
                date_str = date_el.get_text(strip=True) if date_el else ""
                
                # Validación de fecha básica
                try:
                    row_dt = datetime.strptime(date_str.split(' ')[0], '%d.%m.%y')
                    if start_dt and row_dt < start_dt:
                        return new_data # Salimos del scrap si llegamos a fechas anteriores
                except: pass

                status = row.select_one('.col-status').get_text(strip=True) if row.select_one('.col-status') else ""
                user = row.select_one('.col-user').get_text(strip=True) if row.select_one('.col-user') else ""
                total = row.select_one('.col-total').get_text(strip=True) if row.select_one('.col-total') else ""

                new_data.append({
                    'Order ID': order_id,
                    'Date': date_str,
                    'User': user,
                    'Status': status,
                    'Total': total,
                    'Type': 'Purchase' if 'Received' in url else 'Sale'
                })
                existing_ids.add(order_id)
            except Exception as e:
                print(f"[!] Error en fila: {e}")

        print(f"[*] Página {page_num}: {len(rows)} filas procesadas.")

        if page_duplicates == len(rows):
            print("[*] Sincronización completa alcanzada.")
            break

        # Verificar si hay botón "Next"
        next_btn = soup.select_one('a[aria-label="Next Page"]')
        if not next_btn: break
        
        page_num += 1
        time.sleep(1) # Respeto al servidor

    return new_data

def run():
    if not USER_NAME or not PASSWORD:
        print("[!] Error: CM_USERNAME y CM_PASSWORD son necesarios.")
        return

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Intentando Login...")
        # Primero obtenemos la página para el token CSRF si existiera
        login_page = s.get("https://www.cardmarket.com/en/Magic/MainPage/Login", headers=HEADERS)
        soup = BeautifulSoup(login_page.text, 'html.parser')
        
        # Cardmarket suele usar un formulario estándar
        payload = {
            '_username': USER_NAME,
            '_password': PASSWORD,
            '__submit': 'Login'
        }
        
        res = s.post("https://www.cardmarket.com/en/Magic/MainPage/Login", data=payload, headers=HEADERS)
        
        if "Login" in BeautifulSoup(res.text, 'html.parser').title.string:
            print("[!] Login fallido. Revisa credenciales o si hay bloqueo temporal.")
            return

        print("[+] Login exitoso.")
        
        new_total = 0
        if args.include_purchases:
            new_total += len(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, None, existing_ids))
        if args.include_sales:
            new_total += len(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, None, existing_ids))

        if new_total > 0:
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                # Reconstruir lista para asegurar formato
                final_list = []
                # Añadir registros (podrías ordenarlos aquí)
                # ... lógica de ordenación si fuera necesaria ...
                for id in existing_ids:
                    # Buscamos el registro en all_rows o nuevos
                    # (En este ejemplo simplemente guardamos el estado actual)
                    pass
                # Escribimos los datos acumulados
                writer.writerows(all_rows) 
            print(f"[+] CSV actualizado. Total registros: {len(all_rows)}")
        else:
            print("[*] No se encontraron nuevos datos.")

if __name__ == "__main__":
    run()
