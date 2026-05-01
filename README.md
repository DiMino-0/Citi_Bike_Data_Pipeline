# **Citi Bike Data Pipeline**

## **Overview**

**Purpose**: An end-to-end data pipeline that obtains and cleans monthly Citi Bike trip records, performs analysis on ridership patterns, station usage, and member behavior, and makes these results viewable on a web app automatically. Only for NY data.

**Architecture**: Python backend (FastAPI + asyncpg driver + SQLModel) → PostgreSQL database → React frontend (Vite + Node.js) (ascii visualization at bottom)

**Automation**: GitHub Actions deploys Docker Compose services to the DigitalOcean server; monthly data seeding runs as a scheduled loop with FastAPI.

**Project Status**: Hosting was obtained through Digital Ocean. A Postgres database and Ubuntu server were set up remotely with a firewall for dev machine. A FastAPI app running locally was connected to the db with some test routes. Frontend/Backend/DB Docker images created, and compose to define their connections. Nginx to serve static React files, and to act as a reverse proxy (forwards /api to backend). Production runtime is managed by Docker Compose invocations from CI/CD.

## **Data Pipeline**

### **Ingestion**

Fetches monthly data from S3:

- URL pattern: "YYYYMM-citibike-tripdata.csv.zip"
- "JC-" prefix indicates data for Jersey.
- Script polls daily from month start until new dataset is available via cron job and Python script on backing server.
- Uses `requests` (download), `zipfile` (extraction), `io` (file handling), and `pandas` (cleaning/transformation).

### **Processing**

The data has 13 features, as follows:

- **Trip identifiers**: `ride_id`, `rideable_type`
- **Temporal**: `started_at`, `ended_at`
- **Stations**: `start_station_name`, `start_station_id`, `end_station_name`, `end_station_id`
- **Geospatial**: `start_lat`, `start_lng`, `end_lat`, `end_lng`
- **User type**: `member_casual`

Citi Bike the company publishes their system data monthly in GBFS, or General Bikeshare Feed Specification, format. "This data is provided according to the NYCBS Data Use Policy." The data is free to use and can be found [at data city of NY.](https://data.cityofnewyork.us/dataset/Citi-Bike-System-Data/vsnr-94wk/about_data "NYC Open Data") if you want to examine it.

Derived Metrics:

- Ride duration
  - Calculated as the difference between `ended_at` and `started_at`.
- Route + duration
  - Computed using start/end longitude and latitude.
  - Routing logic is currently straight line calculation using haversine miles.
- Station usage
  - Total trip count by station name and station ID.
  - Arrivals and departures tracked per station.
- Actual vs estimated trip duration
  - Compare rider behavior against estimated duration.
  - Used to evaluate:
    - Whether members keep bikes longer than casual riders.
    - Whether electric or classic bikes are favored for longer rides.

Visualizations Made:

- Histograms
  - Number of station uses by:
    - Bike type (classic/electric)
    - Rider type (member/casual)
    - Duration buckets (member/casual)
- Scatter plot
  - Trip duration vs time of day
    - Highlights dense usage windows for member/casual riders.

Conclusions to be Drawn:

- Does rider type (`member` vs `casual`) affect trip duration?
- Does bike type (`classic` vs `electric`) affect:
  - Station usage patterns?
  - Ride duration?

### **Storage**

PostgreSQL database is being used to hold the data on remote. Parquet mode uses local data store.

- Avoiding duplicate code via SQLModel filling a dual role as ORM (SQLAlchemy) and API schema (Pydantic).
- Async operations via `postgresql+asyncpg` driver with `asyncpg` for session management.

## **API**

FastAPI with Uvicorn ASGI server for concurrent connections following RESTful architecture.

**Sample endpoints**:

- `GET /api` - root api route
- `GET /api/db/health` - db status
- `GET /api/engine/info` - info on asyncpg engine
- `GET /api/session/info` - async session info

## **Frontend**

React + Vite stack with data visualization components.

## **Middleware**

- Nginx reverse proxy routes frontend requests to the FastAPI backend.

## **Quick Start (Windows)**

## **Prerequisites**

- Python 3.13+
- PostgreSQL 14+
- Node.js 18+ (frontend)
- First clone the repo and move to the root dir, then follow the below steps.

1. Create and activate a virtual environment using venv (optional but recommended):

   ```cmd
   python3 -m venv your_venv_name
   .venv\Scripts\activate
   ```

2. Install dependencies:

   ```cmd
   python3 -m pip install -r server/requirements.txt
   ```

3. Optional: Set environment variables

   ```.env.example
   DB_URL="postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>"
   SSL_CA_PATH="C:\path\to\ca-certificate.pem"
   DB_ECHO=1
   LOAD_DOTENV=1
   ```

   - Use `.gitignore` for secrets [^gitignore].

4. Start the FastAPI (backend) server. You can use their wrapper or Uvicorn directly.

   Move into the `server` directory, then run either:

   **FastAPI CLI:**

   ```cmd
   python3 -m fastapi dev main.py
   ```

   **Uvicorn directly:**

   ```cmd
   uvicorn main.py --reload
   ```

## **Docker Run (Recommended for Server)**

From the repository root:

```cmd
docker compose up --build -d
```

Check services/logs:

```cmd
docker compose ps
docker compose logs -f frontend backend db
```

Quick API check:

```cmd
curl http://localhost:3000/api/db/health
```

Stop stack:

```cmd
docker compose down
```

## Technologies Used [^badgesSource]

### Infrastructure & DevOps

- [![DigitalOcean](https://img.shields.io/badge/DigitalOcean-%230167ff.svg?style=for-the-badge&logo=digitalOcean&logoColor=white)](https://digitalocean.com)
- ![Docker](https://img.shields.io/badge/docker-%230db7ed.svg?style=for-the-badge&logo=docker&logoColor=white)
- ![Nginx](https://img.shields.io/badge/nginx-%23009639.svg?style=for-the-badge&logo=nginx&logoColor=white)

### Backend

- ![Postgres](https://img.shields.io/badge/postgres-%23316192.svg?style=for-the-badge&logo=postgresql&logoColor=white)
- ![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
- ![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
- ![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?style=for-the-badge)
- ![asyncpg](https://img.shields.io/badge/asyncpg-2C3E50?style=for-the-badge)
- ![pandas](https://img.shields.io/badge/pandas-150458?style=for-the-badge&logo=pandas&logoColor=white)
- ![SQLModel](https://img.shields.io/badge/SQLModel-111827?style=for-the-badge)
- ![SQLAlchemy](https://img.shields.io/badge/sqlalchemy-%23D71F00.svg?style=for-the-badge&logo=sqlalchemy&logoColor=white)
- ![Pydantic](https://img.shields.io/badge/pydantic-%23E92063.svg?style=for-the-badge&logo=pydantic&logoColor=white)

### Frontend

- ![React](https://img.shields.io/badge/react-%2320232a.svg?style=for-the-badge&logo=react&logoColor=%2361DAFB)
- ![Vite](https://img.shields.io/badge/vite-%23646CFF.svg?style=for-the-badge&logo=vite&logoColor=white)
- ![TypeScript](https://img.shields.io/badge/TypeScript-007ACC?style=for-the-badge&logo=typescript&logoColor=white)
- ![TanStack Query](https://img.shields.io/badge/TanStack%20Query-FF4154?style=for-the-badge&logo=reactquery&logoColor=white)
- ![NodeJS](https://img.shields.io/badge/node.js-6DA55F?style=for-the-badge&logo=node.js&logoColor=white)

### Production Architecture ASCII Visualization

```ASCII
         ┌──────────────────────────┐
         │        End User          │
         │  Browser / React Client  │
         │  (Vite-built bundle)     │
         └─────────────┬────────────┘
                       │
                       │ HTTP/HTTPS Requests
                       │ Domain: pending...
                       ▼
┌────────────────────────────────────────────┐
│      APP DROPLET (Digital Ocean)           │
│  ┌────────────────────────────────────┐    │
│  │         NGINX                      │    │
│  │   Reverse Proxy + Static File      │    │
│  │          Server                    │    │
│  │  (serves React index.html +        │    │
│  │   forwards /api to backend)        │    │
│  └───────────┬────────────────────────┘    │
│              │                             │
│  /api/*      │      /* (frontend)          │
│  requests    │      routes served          │
│  proxied     │      as static files        │
│              │                             │
│              ▼                             │
│  ┌──────────────────────────────────┐      │
│  │           Gunicorn               │      │
│  │   (WSGI, Process Manager)        │      │
│  │   manages multiple               │      │
│  │   Uvicorn ASGI workers           │      │
│  │   ┌────────────────────────────┐ │      │
│  │   │   FastAPI App              │ │      │
│  │   │  - API routing             │ │      │
│  │   │  - Pydantic validation     │ │      │
│  │   │  - Error handling          │ │      │
│  │   │  - Business logic          │ │      │
│  │   └───────────┬────────────────┘ │      │
│  └───────────────┼──────────────────┘      │
│                  │                         │
│  ┌───────────────┴────────────────────┐    │
│  │   Data Ingestion (Cron Job)        │    │
│  │  - requests lib (download)         │    │
│  │  - zipfile (extraction)            │    │
│  │  - pandas (cleaning)               │    │
│  │  - asyncpg (postgres insert)       │    │
│  └───────────────┬────────────────────┘    │
│                  │                         │
└──────────────────┼─────────────────────────┘
                   │
                   │ Private network
                   │ SQLAlchemy ORM
                   │ SQLModel schemas
                   │ asyncpg driver
                   │ (connection string with
                   │  DB droplet private IP)
                   ▼
┌────────────────────────────────────────────┐
│    MANAGED DATABASE (Digital Ocean)        │
│  ┌──────────────────────────────────┐      │
│  │      PostgreSQL                  │      │
│  │   - Stores trip data             │      │
│  │   - Cleaned CSV records          │      │
│  │   - Analytics results            │      │
│  │                                  │      │
│  └──────────────────────────────────┘      │
└────────────────────────────────────────────┘
                   ▲
                   │
                   │ Monthly fetch from
                   │ data ingestion cron
                   │
    ┌──────────────┴─────────────┐
    │  Citi Bike S3 Bucket       │
    │     YYYYMM-tripdata.csv.zip│
    └────────────────────────────┘
```

[^badgesSource]: badges from [Ileriayo/markdown-badges](https://github.com/Ileriayo/markdown-badges/tree/master)

[^gitignore]: Generated by [toptal](https://www.toptal.com/developers/gitignore/api)
