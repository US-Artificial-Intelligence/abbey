from ..configs.secrets import CLERK_JWT_PEM, CLERK_SECRET_KEY, CUSTOM_AUTH_SECRET, CUSTOM_AUTH_DB_ENDPOINT, CUSTOM_AUTH_DB_USERNAME, CUSTOM_AUTH_DB_PASSWORD, CUSTOM_AUTH_DB_PORT, CUSTOM_AUTH_DB_NAME
from ..configs.user_config import AUTH_SYSTEM, CUSTOM_AUTH_USE_DATABASE
import jwt
import requests
import pymysql

class FullUser():
    def __init__(
            self,
            user_id,
            first_name,
            last_name,
            email_address,
            image_url  # profile image
        ):
        self.user_id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.email_address = email_address
        self.image_url = image_url
    
    def to_json(self):
        return {
            'id': self.user_id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'email_address': self.email_address,
            'image_url': self.image_url
        }


class Auth():
    def __init__(self, code):
        self.code = code

    # Returns dictionary with keys user_id and email
    def extract_token_info(self, token):
        raise Exception(f"Extract token not implemented for auth with code {self.code}")

    # Return list of FullUsers from emails and user ids
    def get_users(self, emails=[], user_ids=[]):
        raise Exception(f"Get users is not implemented for auth with code {self.code}")


class Clerk(Auth):
    def __init__(self):
        super().__init__(code="clerk")
    
    def extract_token_info(self, token):
        AUTH_ALGO = "RS256"
        data = jwt.decode(token, CLERK_JWT_PEM, algorithms=[AUTH_ALGO], leeway=5)
        email = data['email']
        user_id = data['sub']
        return {'email': email, 'user_id': user_id}

    def _extract_email(self, clerk_json):
        primary_email_id = clerk_json['primary_email_address_id']
        email_addresses = clerk_json['email_addresses']
        email = next(filter(lambda x: x['id'] == primary_email_id, email_addresses))['email_address']
        return email

    def get_users(self, emails=[], user_ids=[]):
        BEARER_TOKEN = CLERK_SECRET_KEY

        # Apparently, Clerk default behavior is to return all users when you submit an empty request
        if len(emails) == 0 and len(user_ids) == 0:
            return []

        # The API endpoint
        url = 'https://api.clerk.com/v1/users'

        # Set up the headers, including the Bearer token
        headers = {
            'Authorization': f'Bearer {BEARER_TOKEN}',
        }

        email_tups = [('email_address', email) for email in emails]
        id_tups = [('user_id', id) for id in user_ids]

        # NOTE: One day, someone's gonna realize that the limit is 500 and come here and think wow, hardcoding this value was dumb
        params = [
            ('limit', 500),
            ('offset', 0),
            ('order_by', '-created_at'),
            *email_tups,
            *id_tups
        ]

        # Send the GET request
        response = requests.get(url, headers=headers, params=params)

        # Check if the request was successful
        if response.status_code == 200:
            users = response.json()
            full_users = [
                FullUser(
                    user_id=x['id'],
                    first_name=x['first_name'] if 'first_name' in x else '',
                    last_name=x['last_name'] if 'last_name' in x else '',
                    email_address=self._extract_email(x),
                    image_url=x['image_url'] if 'image_url' in x else ''
                ) for x in users
            ]
            return full_users
        else:
            raise Exception("Could not make request to Clerk.")


class CustomAuth(Auth):
    def __init__(self):
        super().__init__(code="custom")
        if AUTH_SYSTEM != self.code:
            pass
        elif CUSTOM_AUTH_USE_DATABASE:
            db_params = {
                'host': CUSTOM_AUTH_DB_ENDPOINT,
                'user': CUSTOM_AUTH_DB_USERNAME,
                'passwd': CUSTOM_AUTH_DB_PASSWORD,
                'port': int(CUSTOM_AUTH_DB_PORT),
                'database': CUSTOM_AUTH_DB_NAME,
                'cursorclass': pymysql.cursors.DictCursor
            }
            self.conn = pymysql.connect(**db_params)
    
    def extract_token_info(self, token):
        AUTH_ALGO = "HS256"
        data = jwt.decode(token, CUSTOM_AUTH_SECRET, algorithms=[AUTH_ALGO], leeway=5)
        email = data['email']
        user_id = data['sub']
        return {'email': email, 'user_id': str(user_id)}

    def get_users(self, emails=[], user_ids=[], tries=0):
        if not CUSTOM_AUTH_USE_DATABASE:
            return []
        
        # Basically this is set up to be somewhat stable; errors that involve connections timing out etc will automatically ping to reconnect and try again.
        if tries < 2:
            try:
                curr = self.conn.cursor()
                sql = f"""
                    SELECT * FROM users
                """
                if len(emails):
                    sql += f"\n WHERE `email` IN ({','.join([self.conn.escape_string(x) for x in emails])})"
                if len(user_ids):
                    sql += f"\n WHERE `id` IN ({','.join([self.conn.escape_string(x) for x in user_ids])})"
                curr.execute(sql)
                res = curr.fetchall()
                full_users = [
                    FullUser(
                        user_id=x['id'],
                        first_name=x['first_name'] if 'first_name' in x else '',
                        last_name=x['last_name'] if 'last_name' in x else '',
                        email_address=x['email'],
                        image_url=x['image_url'] if 'image_url' in x else ''
                    ) for x in res
                ]
                return full_users
            except (pymysql.OperationalError, pymysql.InterfaceError) as e:
                self.curr.ping(reconnect=True)
                self.get_users(emails=emails, user_ids=user_ids, tries=tries+1)



AUTH_PROVIDERS = {
    'clerk': Clerk(),
    'custom': CustomAuth()
}