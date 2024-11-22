import os
import dotenv
import requests
import pandas as pd
import psycopg2 as pg
import sqlite3 as sqlt
import sqlalchemy as sa

from datetime import date

from tqdm import tqdm
from collections import defaultdict

def connect_to_database():
    return pg.connect(database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'), port=os.getenv('DB_PORT'), host=os.getenv('DB_HOST'))

def call_ml_api(category: str, limit: int = 50, offset: int = 0, print_status: bool = True):
    return requests.get(f'https://api.mercadolibre.com/sites/MLB/search', params={'category':category, 'limit':limit, 'offset':offset})

if __name__ == '__main__':
    dotenv.load_dotenv()

    keys_to_drop = ['sale_price', 'shipping', 'seller', 'address', 'attributes', 'installments', 'promotions', 'official_store_name', 'variations_data', 'variation_filters', 
    'thumbnail_id', 'catalog_product_id', 'sanitized_title', 'buying_mode', 'site_id', 'category_id', 'order_backend', 'use_thumbnail_id', 'accepts_mercadopago', 'stop_time', 
    'catalog_listing','winner_item_id', 'discounts', 'decorations', 'inventory_id', 'permalink', 'domain_id', 'thumbnail']

    api_request = call_ml_api(category='MLB99245')

    total_items = api_request.json()['paging']['total']
    groups_of_50 = total_items//50
    remanescent_group = total_items%50

    control_dict = defaultdict(list)

    today = date.today()

    for api_call in tqdm(range(groups_of_50+2)):
        offset = 50*api_call
        if offset > total_items: offset = 50*groups_of_50+remanescent_group

        request = call_ml_api(category='MLB99245', offset=offset)

        if request.status_code != requests.codes.ok: 
            print('\nBad Request', request.status_code)
            break

        for result in request.json()['results']:

            for key in [key for key in result.keys() if key not in keys_to_drop]:
                control_dict[key].append(result[key])

            control_dict['item_brand'].append(result['attributes'][1]['value_name'])
            control_dict['item_color'].append(result['attributes'][2]['value_name'])

            control_dict['api_request_day'].append(today)

    temp_con = sqlt.connect(r'C:\Users\pedro\OneDrive\coding\mercado_livre_API\temp.db')
    temp_cursor =  temp_con.cursor()
    temp_cursor.execute('''CREATE TABLE IF NOT EXISTS ml_api_dados
    (id text, title text, condition text, listing_type_id text, currency_id text,
    price real, original_price real, available_quantity integer, item_color text,
    official_store_id real, item_brand text, api_request_day text);''')
    temp_con.commit()
    temp_cursor.execute('SELECT COUNT(*) FROM ml_api_dados;')
    temp_con.commit()
    print('SQLite: ',temp_cursor.fetchone())
    temp_cursor.close()

    sqlite_engine = sa.create_engine(r"sqlite:///C:\Users\pedro\OneDrive\coding\mercado_livre_API\temp.db")
    pd.DataFrame(control_dict).to_sql(name='ml_api_dados', con=sqlite_engine.connect(), if_exists='append', index=False)

    pg_df = pd.read_sql_query('SELECT * FROM ml_api_dados', temp_con)

    db_connection = connect_to_database()
    db_connection.autocommit = True
    with db_connection.cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS ml_api_dados
        (id text, title text, condition text, listing_type_id text, currency_id text,
        price float8, original_price float8, available_quantity int4, item_color text,
        official_store_id float8, item_brand text, api_request_day date);''')
        cursor.execute('SELECT COUNT(*) FROM ml_api_dados;')
        print('PGSQL ', cursor.fetchone())

    engine = sa.create_engine(f'postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}')
    pg_df.to_sql(name='ml_api_dados', con=engine.connect(), if_exists='append', index=False)
