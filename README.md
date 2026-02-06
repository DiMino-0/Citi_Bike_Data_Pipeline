# **Citi Bike Data Pipeline**

## **Overview**

**Purpose**: An end-to-end data pipeline that obtains and cleans monthly Citi Bike trip records, performs analysis on ridership patterns, station usage, and member behavior, and makes these results viewable on a web app automatically.

**Architecture**: Python backend (FastAPI + asyncpg driver + SQLModel + PDM) → PostgreSQL database → React frontend (Vite + Node.js)

**Automation**: Digital Ocean server runs scheduled Python script for monthly data ingestion.

**Project Status**: Hosting was obtained through Digital Ocean. A Postgres database and Ubuntu server were set up remotely with a firewall for dev machine. A FastAPI app running locally was connected to the db with some test routes. middleware added: CORS.

## **Data Pipeline**

### **Ingestion**

Fetches monthly data from S3:

- URL pattern: "YYYYMM-citibike-tripdata.csv.zip"
- "JC-" prefix indicates data for jersey
- Script polls daily from month start until new dataset available,
  via cron job and py script on backing server
- Uses `requests` (download), `zipfile` (extraction), `io` (file handling), pandas (cleaning/transformation)

### **Processing**

The data has 13 features, as follows:

- **Trip identifiers**: `ride_id`, `rideable_type`
- **Temporal**: `started_at`, `ended_at`
- **Stations**: `start_station_name`, `start_station_id`, `end_station_name`, `end_station_id`
- **Geospatial**: `start_lat`, `start_lng`, `end_lat`, `end_lng`
- **User type**: `member_casual`

Citi Bike the company publishes their system data monthly in GBFS, or General Bikeshare Feed Specification, format. "This data is provided according to the NYCBS Data Use Policy." The data is free to use and can be found [here](https://data.cityofnewyork.us/dataset/Citi-Bike-System-Data/vsnr-94wk/about_data "NYC Open Data") if you want to examine it.

Derived Metrics: tbd

Visualizations Made: tbd

Conclusions Drawn: tbd

### **Storage**

PostgreSQL 18 database is being used to hold all the data.

- Avoiding duplicate code via SQLModel filling a dual role as ORM (SQLAlchemy) and API schema (Pydantic)
- Async operations via postgresql+asyncpg driver with asyncpg for session management.

## **API**

FastAPI with Uvicorn ASGI server for concurrent connections.

**Sample endpoints**:

- `GET /db/health` - db status
- `GET /engine/info` - info on asyncpg engine
- `GET /session/info` - async session info

## **Middleware**

- CORS (Cross-Origin Resource Sharing) was implemented to allow safe back-front end communication.

## **Frontend**

React + Vite stack with data visualization components. The react app makes HTTP requests to FastAPI endpoints, receives JSON responses in turn.

## **Prerequisites**

- Python 3.13+
- PostgreSQL 14+
- Node.js 18+ (frontend)

## **Quick Start (Windows)**

First clone the repo and move to the root dir, then follow the below steps.

1. Create and activate a virtual environment using venv (optional but recommended):

   ```cmd
   python3 -m venv your_venv_name
   .venv\Scripts\activate
   ```

2. Install dependencies:

   ```cmd
   python3 -m pip install -r requirements.txt
   ```

3. Optional - Set environment variables

   ```.env
   DB_URL="postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>"
   SSL_CA_PATH="C:\path\to\ca-certificate.pem"
   CORS_ALLOWED_ORIGINS="http://127.0.0.1:8000,http://localhost:8000"
   DB_ECHO=1
   LOAD_DOTENV=1
   ```

   - use gitignore for secrets [^gitignore]

   **CORS note:** `CORS_ALLOWED_ORIGINS` can be set to a comma-separated list of allowed origins (for example: `"http://127.0.0.1:8000,http://localhost:8000"`). If unset, the server defaults to a restrictive set of local development origins (127.0.0.1:8000 and 127.0.0.1:8000).

4. Start FastAPI (backend) server, you can use their wrapper or Uvicorn directly

   Move into the server dir, then run either

   **FastAPI CLI:**

   ```cmd
   python3 -m fastapi dev main.py
   ```

   **Uvicorn directly:**

   ```cmd
   uvicorn main.py --reload
   ```

## Technologies Used [^badgesSource]

- [![DigitalOcean](https://img.shields.io/badge/DigitalOcean-%230167ff.svg?style=for-the-badge&logo=digitalOcean&logoColor=white)](https://digitalocean.com)
- ![Postgres](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
- ![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
- SQLMODEL (powered by Pydantic and SQLAlchemy.)
- ![SQLAlchemy](https://img.shields.io/badge/sqlalchemy-%23D71F00.svg?style=for-the-badge&logo=sqlalchemy&logoColor=white)
- ![Pydantic](https://img.shields.io/badge/pydantic-%23E92063.svg?style=for-the-badge&logo=pydantic&logoColor=white)
- ![React](https://img.shields.io/badge/react-%2320232a.svg?style=for-the-badge&logo=react&logoColor=%2361DAFB)
- ![Vite](https://img.shields.io/badge/vite-%23646CFF.svg?style=for-the-badge&logo=vite&logoColor=white)
- ![NodeJS](https://img.shields.io/badge/node.js-6DA55F?style=for-the-badge&logo=node.js&logoColor=white)

[^badgesSource]: badges from [Ileriayo/markdown-badges](https://github.com/Ileriayo/markdown-badges/tree/master)

[^gitignore]: Generated by [toptal](https://www.toptal.com/developers/gitignore/api)
