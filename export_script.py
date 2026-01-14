
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
# MÉTODO RECOMENDADO: Copia tu cookie 'PHPSESSID' desde el navegador
CM_COOKIE = os.environ.get('CM_COOKIE') 

CSV_FILE = 'cardmarket_export.csv'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
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
        try:
            response = session.get(paginated_url, headers=HEADERS, timeout=15)
            if response.status_code == 401:
                print("[!] Error 401: Sesión no válida o expirada.")
                break
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Verificar si realmente estamos dentro
            if not any('Logout' in a.get('href', '') for a in soup.find_all('a', href=True)):
                print("[!] No parece haber una sesión activa en esta página.")
                break

            table_body = soup.select_one('div.table-body')
            if not table_body:
                print("[*] No se encontraron datos en esta página.")
                break
                
            rows = table_body.select('div.row')
            if not rows: break

            page_duplicates = 0
            for row in rows:
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
                        print(f"[*] Fecha límite alcanzada ({date_str}).")
                        return new_data
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

            print(f"[*] Página {page_num}: {len(new_data)} nuevos pedidos.")

            if page_duplicates == len(rows) and len(rows) > 0:
                print("[*] Sincronización completa.")
                break

            if not soup.select_one('a[aria-label="Next Page"]'):
                break
            
            page_num += 1
            time.sleep(2)
        except Exception as e:
            print(f"[!] Error en scrap: {e}")
            break

    return new_data

def run():
    existing_ids, all_rows = load_existing_data()
    start_dt = datetime(int(args.year), 1, 1) if args.year else None

    with requests.Session() as s:
        if CM_COOKIE:
            print("[*] Usando Cookie de sesión manual...")
            # Formato esperado: "PHPSESSID=xxxxxxx; ..."
            s.headers.update({'Cookie': CM_COOKIE})
        else:
            print("[*] Intentando Login automático (Tradicional)...")
            login_url = "https://www.cardmarket.com/en/Magic/MainPage/Login"
            r = s.get(login_url, headers=HEADERS)
            soup = BeautifulSoup(r.text, 'html.parser')
            form = soup.find('form')
            
            if not form:
                print("[!] Error: No se encontró el formulario. Cardmarket está usando Login por JS.")
                print("[!] POR FAVOR: Usa el método de CM_COOKIE (ver README).")
                return

            payload = {tag.get('name'): tag.get('value', '') for tag in form.find_all('input') if tag.get('name')}
            payload['_username'] = USER_NAME
            payload['_password'] = PASSWORD
            
            action = form.get('action', login_url)
            if not action.startswith('http'): action = "https://www.cardmarket.com" + action
            
            s.post(action, data=payload, headers={**HEADERS, 'Referer': login_url})

        # Validar sesión visitando el perfil
        check = s.get("https://www.cardmarket.com/en/Magic", headers=HEADERS)
        if 'Logout' not in check.text:
            print("[!] SESIÓN NO ACTIVA. Si el login automático falló, usa el método CM_COOKIE.")
            return
        
        print("[+] Sesión confirmada.")

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
            print(f"[+] Finalizado. {len(new_items)} nuevos pedidos guardados.")
        else:
            print("[*] No hay pedidos nuevos.")

if __name__ == "__main__":
    run()
