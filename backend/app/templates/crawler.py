from .template import Template
from ..db import needs_db
from ..auth import User
import sqlite3
import tempfile
import os
from ..asset_actions import add_asset_resource, get_asset_resource
from ..storage_interface import download_file, replace_asset_file, upload_asset_file
from ..configs.str_constants import MAIN_FILE
from flask_cors import cross_origin
from ..auth import token_optional
from flask import Blueprint, request
from ..template_response import MyResponse
import os


bp = Blueprint('crawler', __name__, url_prefix="/crawler")


# TODO move this into the CrawlerDB class
def create_and_upload_database(asset_id):
    temp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False)
    db_path = temp_file.name
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        sql = """
            CREATE TABLE websites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                scraped_at DATETIME,      
                title TEXT,
                author TEXT,
                url TEXT
            )
        """
        cursor.execute(sql)
        # Commit the changes
        conn.commit()

        path, from_key = upload_asset_file(asset_id, temp_file.name, 'sqlite')
        add_asset_resource(asset_id, MAIN_FILE, from_key, path, "Database")

    finally:
        # Close the connection
        conn.close()

        # Delete the temporary database file
        if os.path.exists(db_path):
            os.remove(db_path)


# Wrapers around db functions
# In the future, doesn't necessarily need to be sqlite
class CrawlerDBResult():
    def __init__(self, res):
        self.res = res  # As of rn, a sqlite result
    
    def fetchall(self):
        return self.res.fetchall()
    
    def fetchone(self):
        return self.res.fetchone()

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class CrawlerDB():
    def __init__(self, asset_id):
        # Somewhat inefficient in that there's no caching
        # And requires downloading the entire DB
        res = get_asset_resource(asset_id, MAIN_FILE)
        if res is None:
            raise Exception(f"Couldn't find any existing crawler database for asset id {asset_id}")
        self.asset_resource = res

        tmp = tempfile.NamedTemporaryFile(delete=False)
        download_file(tmp.name, res)
        self.path = tmp.name
        conn = sqlite3.connect(self.path)
        conn.row_factory = dict_factory
        self.conn = conn
        self.asset_id = asset_id

    def execute(self, *args, **kwargs):
        res = self.conn.execute(*args, **kwargs)
        res = CrawlerDBResult(res)
        return res
    
    # Also reuploads DB
    def commit(self, *args, **kwargs):
        self.conn.commit()
        replace_asset_file(self.asset_resource['from'], self.asset_resource['path'], self.path)

    # Deletes file in addition to closing connection
    def close(self, *args, **kwargs):
        self.conn.close(*args, **kwargs)
        os.remove(self.path)


@bp.route('/manifest', methods=('GET',))
@cross_origin()
@token_optional
def get_manifest(user: User):
    asset_id = request.args.get('id')

    limit = int(request.args.get('limit', 30))
    if limit > 500:
        limit = 500

    offset = request.args.get('offset', 0)

    conn = CrawlerDB(asset_id)

    # Query to get the total number of results
    # Annoyingly run the query twice to get a "total"
    sql = """
        SELECT COUNT(*) as _total FROM websites
    """
    res = conn.execute(sql)
    total = res.fetchone()['_total']
    
    # Actual query
    sql = """
        SELECT * FROM websites ORDER BY `created_at` DESC LIMIT ? OFFSET ?
    """
    res = conn.execute(sql, (limit, offset))
    results = res.fetchall()

    conn.close()  # Very important

    return MyResponse(True, {'results': results, 'total': total}).to_json()


class Crawler(Template):
    def __init__(self) -> None:
        super().__init__()
        self.chattable = False
        self.summarizable = False
        self.code = "crawler"

    @needs_db
    def upload(self, user: User, asset_id, asset_title="", using_auto_title=False, using_auto_desc=False, db=None):
        # Create the initial sqlite database file and store it
        create_and_upload_database(asset_id)
        return True, asset_id