import unittest
from flask import Flask
from app.routes import init_routes

class RSITestCase(unittest.TestCase):
    
    def setUp(self):
        app = Flask(__name__)
        init_routes(app)
        app.config['TESTING'] = True
        self.app = app.test_client()

    def tearDown(self):
        pass

    def test_busca_rsi_por_intervalo(self):
        response = self.app.get('/rsi/5m')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, dict)
        self.assertIn('results', data)
        self.assertIn('errors', data)
        for result in data['results']:
            self.assertIn('current_price', result)

if __name__ == '__main__':
    unittest.main()
