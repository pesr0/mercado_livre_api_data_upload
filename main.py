import os
import dotenv
import requests
import pandas as pd
import psycopg2 as pg
import sqlite3 as sqlt
import sqlalchemy as sa

from tqdm import tqdm
from datetime import date
from collections import defaultdict

def connect_to_pg_database(db_name: str, username: str, password: str, db_port: str, host: str):
    '''
    Connects to Postgrees SQL database.

    Args:
    db_name, str: Database's name
    username, str: Database's username
    password, str: Databese's password
    db_port, str: Host connection port
    host, str: Host connection url

    Returns:
    pg.connection object
    '''
    return pg.connect(database=db_name, user=username, password=password, port=db_port, host=host)

def call_ml_api(category_id: str, limit: int = 50, offset: int = 0):
    '''
    Creates a request from Mercado Livre's API.

    Args:
    category_id, str: ID of the category of the desired items
    limit, int: Limit of items returned by the request (min: 1, max: 50)
    offset, int: Offset os the items returned relative to the default ones (e.g. offset=10 & limit = 50, returns 50 items after the first 10 items)

    Returns:
    requests.Response object
    '''
    return requests.get(f'https://api.mercadolibre.com/sites/MLB/search', params={'category':category_id, 'limit':limit, 'offset':offset})

def create_table_if_not_exists(database_service: str, table_name: str, conn: sa.Connection) -> None:
    '''
    Creates pre-defined table into connected database if that table does not exist.
    Databases available are SQLite and PostgresDB.

    Args:
    database_service, str (sqlite or postgres)
    table_name, str
    conn, sqlalchemy.Connection: Connection object

    Returns:
    None
    '''

    if database_service not in ['sqlite', 'postgres']: raise ValueError(f'{database_service} not available for database_service')

    if database_service == 'sqlite':
        int_value = 'integer'
        float_value = 'real'
        date_value = 'text'
    if database_service == 'postgres':
        int_value = 'int4'
        float_value = 'float8'
        date_value = 'date'

    temp_cursor =  conn.cursor()

    temp_cursor.execute(f'''CREATE TABLE IF NOT EXISTS {table_name}
    (id text, title text, condition text, listing_type_id text, currency_id text, item_hz text, item_ms text,
    price {float_value}, original_price {float_value}, available_quantity {int_value}, item_color text,
    official_store_id {float_value}, item_brand text, item_package_length text, api_request_day {date_value});''')
    conn.commit()

    temp_cursor.close()

    return

if __name__ == '__main__':
    # load env vars
    dotenv.load_dotenv()

    # fields dropped from the API request (these fields are either not useful for us or are composed by data structures which need to be treated first)
    keys_to_drop = ['sale_price', 'shipping', 'seller', 'address', 'attributes', 'installments', 'promotions', 'official_store_name', 'variations_data', 'variation_filters', 
    'thumbnail_id', 'catalog_product_id', 'sanitized_title', 'buying_mode', 'site_id', 'category_id', 'order_backend', 'use_thumbnail_id', 'accepts_mercadopago', 'stop_time', 
    'catalog_listing','winner_item_id', 'discounts', 'decorations', 'inventory_id', 'permalink', 'domain_id', 'thumbnail']

    api_request = call_ml_api(category_id='MLB99245')

    # vars created for iteration control. Since we have limited values of offset and limit for the requests, it is needed to do some iterations adjusting the offset
    total_items = api_request.json()['paging']['total']
    groups_of_50 = total_items//50

    # dict for rows appending, in order to create the df in one single step at the end
    control_dict = defaultdict(list)

    today = date.today()

    # since our limit of items per request is 50, we need to make at least groups_of_50 iterations to get all of the items
    for api_call in tqdm(range(groups_of_50+2)):
        offset = 50*api_call
        if offset > total_items: offset = total_items

        request = call_ml_api(category_id='MLB99245', offset=offset)

        # Mercado Livre's API limits the offset value to 1000, so when that happens, the for loop ends
        if request.status_code != requests.codes.ok: 
            break
        
        for request_item in request.json()['results']:

            for key in [key for key in request_item.keys() if key not in keys_to_drop]:
                control_dict[key].append(request_item[key])

            control_dict['api_request_day'].append(today)

            item_brand = None
            item_color = None
            item_package_length = None
            for attribute_item in request_item['attributes']:

                match attribute_item['id']:
                    case 'BRAND': item_brand = attribute_item['value_name']
                    case 'COLOR': item_color = attribute_item['value_name']
                    case 'PACKAGE_LENGTH': item_package_length = attribute_item['value_name']
                
                if item_brand and item_color and item_package_length: break

            control_dict['item_brand'].append(item_brand)
            control_dict['item_color'].append(item_color)
            control_dict['item_package_length'].append(item_package_length)

            item_hz = None
            item_ms = None
            sanitized_title = request_item['sanitized_title'].split('-')
            for item in sanitized_title:
                if 'hz' in item: item_hz = item
                if 'ms ' in str(item+ ' '): item_ms = item
                if item_hz and item_ms: break
                
            control_dict['item_hz'].append(item_hz)
            control_dict['item_ms'].append(item_ms)

    # Connects to sqlite db, creates table and insert data gathered in it
    sqlite_con = sqlt.connect(r'C:\Users\pedro\OneDrive\coding\mercado_livre_API\temp.db')
    create_table_if_not_exists('sqlite', 'ml_api_dados', sqlite_con)
    sqlite_engine = sa.create_engine(r"sqlite:///C:\Users\pedro\OneDrive\coding\mercado_livre_API\temp.db")
    pd.DataFrame(control_dict).to_sql(name='ml_api_dados', con=sqlite_engine.connect(), if_exists='append', index=False)

    sqlite_table_as_df = pd.read_sql_query('SELECT * FROM ml_api_dados', sqlite_con)

    # Insert data retrived from SQlite db into Postgres db
    # There is a reason why the data first goes into a SQlite DB and only then to a Postgres DB. Check documentation on github if you want to understand why
    db_connection = connect_to_pg_database(db_name = os.getenv('DB_NAME'), username = os.getenv('DB_USER'), password = os.getenv('DB_PASSWORD'), db_port = os.getenv('DB_PORT'), host = os.getenv('DB_HOST'))
    create_table_if_not_exists('postgres', 'ml_api_dados', db_connection)
    engine = sa.create_engine(f'postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}/{os.getenv('DB_NAME')}')
    sqlite_table_as_df.to_sql(name='ml_api_dados', con=engine.connect(), if_exists='replace', index=False)