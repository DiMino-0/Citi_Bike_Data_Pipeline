# Goal

This project seeks to build an end-to-end data pipeline that automatically fetches the updated system data from Citi Bike each month performing cleaning, visualization, and analysis. These results and figures will then be shown on a web app.

# The Data

Citi Bike the company publishes their system data monthly in GBFS, or General Bikeshare Feed Specification, format. "This data is provided according to the NYCBS Data Use Policy." The data is free to use and can be found [here](https://data.cityofnewyork.us/dataset/Citi-Bike-System-Data/vsnr-94wk/about_data "NYC Open Data").

# Quick Start

1. Create and activate a virtual environment (optional but recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```
   python3 -m pip install -r requirements.txt
   ```

3. Set environment variables

   ```python
   # On Windows (PowerShell):
   $env:DB_URL="postgresql://<user>:<password>@<host>:<port>/<database>"
   $env:SSL_CA_PATH="C:\path\to\ca-certificate.pem"
   ```

4. Start FastAPI server

   ```
   FastAPI CLI: python -m fastapi dev server.main:app
   Uvicorn directly: uvicorn server.main:app --reload
   ```

# Project Status

A Postgres database was set up, hosted through Digital Ocean.

# Technologies Used [^badgesSource]

- [![DigitalOcean](https://img.shields.io/badge/DigitalOcean-%230167ff.svg?style=for-the-badge&logo=digitalOcean&logoColor=white)](https://digitalocean.com)
- ![Postgres](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
- ![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)

[^badgesSource]: badges from Ileriayo/markdown-badges
