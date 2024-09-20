# API RSI para Criptomoedas

## Descrição

A **API RSI** é um serviço projetado para fornecer dados em tempo real sobre o Índice de Força Relativa (RSI) de várias criptomoedas. Desenvolvida com **Flask** e **PostgreSQL**, a API permite que desenvolvedores integrem dados de RSI em suas aplicações, proporcionando informações valiosas para análises de mercado.

## Funcionalidades

- **Cálculo do RSI:** Calcula o RSI para diferentes intervalos de tempo (5m, 30m, 1h, 4h).
- **Armazenamento Dinâmico:** Armazena dados de RSI em um banco de dados PostgreSQL.
- **Cache Eficiente:** Utiliza Redis para armazenar em cache os dados frequentemente acessados, melhorando a performance.
- **APIs RESTful:** Oferece endpoints intuitivos para acesso a dados.

## Tecnologias Utilizadas

- **Linguagem:** Python
- **Framework:** Flask
- **Banco de Dados:** PostgreSQL
- **Cache:** Redis
- **Bibliotecas:** 
  - `ccxt` para integração com a Binance
  - `SQLAlchemy` para ORM
  - `psycopg2` para conexão com PostgreSQL

## Estrutura do Projeto

```plaintext
project/
│
├── app/
│   ├── __init__.py
│   ├── routes.py
│   └── utils.py
│
├── database/
│   ├── __init__.py
│   └── models.py
│
├── services/
│   ├── __init__.py
│   └── binance_service.py
│
├── tests/
│   ├── __init__.py
│   └── test_app.py
│
├── main.py
└── requirements.txt
````
## Instalação

### Pré-requisitos

Certifique-se de ter o **Python 3.x** instalado. Além disso, você precisa do **PostgreSQL** e do **Redis** configurados em sua máquina.

### Passos

1. Clone este repositório:
   ```bash
   git clone https://github.com/seu-usuario/API_RSI.git
   cd API_RSI
````
### Passos

1. Crie um ambiente virtual e ative-o:
   ```bash
   python -m venv env
   # No Windows:
   env\Scripts\activate
   # No macOS/Linux:
   source env/bin/activate
````
### Instalação

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
````
2. Configure a conexão com o banco de dados no arquivo de configuração.

3. Execute a API:
   ```bash
   python main.py
````
## Uso

Acesse a API através dos seguintes endpoints:

- **GET /api/rsi**: Retorna os dados de RSI para uma criptomoeda específica.
- **GET /api/rsi/\<pair>**: Retorna os dados de RSI para um par de criptomoedas específico.

## Contribuições

Contribuições são bem-vindas! Sinta-se à vontade para abrir um **issue** ou fazer um **pull request**.

## Licença

Este projeto está licenciado sob a **MIT License**. Consulte o arquivo [LICENSE](LICENSE) para mais informações.

---
Feito com ❤️ por [Kennedy Ramos](https://github.com/KennnedyRamos)
## 👤 Contato

**Desenvolvedor**: Kennedy Ramos  
**Email**: [kennedy_ramos9@icloud.com](mailto:kennedy_ramos9@icloud.com)  
**LinkedIn**: [linkedin.com/in/kennedy-ramos](https://www.linkedin.com/in/kennedy-silva-ramos-566b00150/)

Conecte-se conosco nas redes sociais:  
🔗 [Instagram](https://www.instagram.com/kennedyramos_/) | 🌐 [Site Oficial](https://kennnedyramos.github.io/meu-postifolio-web/)
