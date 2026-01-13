
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

# Headers optimizados para evitar detecciones y errores de sesión
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/...;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
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

def scrape_section(session, url, start_dt, existing_ids):
    print(f"[*] Accediendo a: {url}")
    new_data = []
    page_num = 1
    
    while True:
        paginated_url = f"{url}?site={page_num}"
        # Es fundamental enviar el Referer en cada petición de scrap
        scrape_headers = HEADERS.copy()
        scrape_headers['Referer'] = "https://www.cardmarket.com/en/Magic"
        
        response = session.get(paginated_url, headers=scrape_headers)
        
        if response.status_code == 401:
            print("[!] Error 401: Sesión no válida. Intentando refrescar sesión...")
            return new_data
            
        if response.status_code != 200:
            print(f"[!] Error {response.status_code} en página {page_num}.")
            break
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Validar si seguimos logueados
        if not any('Logout' in a.get('href', '') for a in soup.find_all('a', href=True)):
            print("[!] Sesión perdida. Deteniendo scrap.")
            break

        table_body = soup.select_one('div.table-body')
        if not table_body:
            print("[!] No se encontró la tabla. ¿No hay pedidos en esta sección?")
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
                
                try:
                    row_dt = datetime.strptime(date_str.split(' ')[0], '%d.%m.%y')
                    if start_dt and row_dt < start_dt:
                        print(f"[*] Fin de rango de fecha ({date_str}).")
                        return new_data
                except: pass

                status = row.select_one('.col-status').get_text(strip=True) if row.select_one('.col-status') else ""
                user = row.select_one('.col-user').get_text(strip=True) if row.select_one('.col-user') else ""
                total = row.select_one('.col-total').get_text(strip=True) if row.select_one('.col-total') else ""

                entry = {
                    'Order ID': order_id,
                    'Date': date_str,
                    'User': user,
                    'Status': status,
                    'Total': total,
                    'Type': 'Purchase' if 'Received' in url else 'Sale'
                }
                new_data.append(entry)
                existing_ids.add(order_id)
            except Exception as e:
                print(f"[!] Error procesando pedido: {e}")

        print(f"[*] Página {page_num}: {len(rows)} encontrados, {len(new_data)} nuevos.")

        if page_duplicates == len(rows):
            print("[*] Sincronización al día en esta sección.")
            break

        if not soup.select_one('a[aria-label="Next Page"]'):
            break
        
        page_num += 1
        time.sleep(2)

    return new_data

def run():
    if not USER_NAME or not PASSWORD:
        print("[!] CM_USERNAME y CM_PASSWORD no definidos.")
        return

    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        print("[*] Obteniendo cookies y token de seguridad...")
        login_url = "https://www.cardmarket.com/en/Magic/MainPage/Login"
        
        # 1. Obtener la página de login para cookies y CSRF
        r_init = s.get(login_url, headers=HEADERS)
        soup_init = BeautifulSoup(r_init.text, 'html.parser')
        
        # Extraer token CSRF y URL de acción del formulario
        form = soup_init.find('form', attrs={'action': True})
        action_url = form['action'] if form else login_url
        if not action_url.startswith('http'):
            action_url = "https://www.cardmarket.com" + action_url
            
        csrf_token = ""
        csrf_input = soup_init.find('input', attrs={'name': '_csrf_token'})
        if csrf_input:
            csrf_token = csrf_input.get('value', '')
            print("[*] Token CSRF extraído.")

        # 2. Ejecutar POST de Login
        payload = {
            '_username': USER_NAME,
            '_password': PASSWORD,
            '_csrf_token': csrf_token,
            '__submit': 'Login'
        }
        
        login_headers = HEADERS.copy()
        login_headers['Referer'] = login_url
        login_headers['Content-Type'] = 'application/x-www-form-urlencoded'
        
        print("[*] Enviando credenciales...")
        res = s.post(action_url, data=payload, headers=login_headers, allow_redirects=True)
        
        # 3. Paso crítico: Visitar el dashboard para asentar la sesión
        # Algunos sitios requieren este paso para activar las cookies de sesión
        s.get("https://www.cardmarket.com/en/Magic", headers=HEADERS)
        
        # 4. Validar éxito
        soup_check = BeautifulSoup(res.text, 'html.parser')
        is_logged = any('Logout' in a.get('href', '') for a in soup_check.find_all('a', href=True))
        
        if is_logged or res.status_code == 200:
            print("[+] Login confirmado. Sesión establecida.")
        else:
            print("[!] Fallo de autenticación. Verifica tus credenciales.")
            return

        new_items = []
        if args.include_purchases:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Orders/Received", start_dt, existing_ids))
        if args.include_sales:
            new_items.extend(scrape_section(s, "https://www.cardmarket.com/en/Magic/Sales/Sent", start_dt, existing_ids))

        if new_items:
            all_rows.extend(new_items)
            keys = ['Order ID', 'Date', 'User', 'Status', 'Total', 'Type']
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(all_rows)
            print(f"[+] Éxito. CSV actualizado con {len(new_items)} pedidos nuevos.")
        else:
            print("[*] No hay pedidos nuevos que procesar.")

if __name__ == "__main__":
    run()
