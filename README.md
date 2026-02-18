# **Citi Bike Data Pipeline**

## **Overview**

**Purpose**: An end-to-end data pipeline that obtains and cleans monthly Citi Bike trip records, performs analysis on ridership patterns, station usage, and member behavior, and makes these results viewable on a web app automatically.

**Architecture**: Python backend (FastAPI + asyncpg driver + SQLModel + PDM) → PostgreSQL database → React frontend (Vite + Node.js)

**Automation**: Digital Ocean server runs scheduled Python script for monthly data ingestion.

**Project Status**: Hosting was obtained through Digital Ocean. A Postgres database and Ubuntu server were set up remotely with a firewall for dev machine. A FastAPI app running locally was connected to the db with some test routes. Frontend/Backend/DB Docker images created, and compose to define their connections. Nginx to serve static React files, and to act as a reverse proxy (forwards /api to backend).

**Currently working on:**

- Backend: Systemd service for server, ingestion script w/ cron job.
- Frontend: Navigation and server state management (React Router, TanStack Query).

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
- Optimal route + duration
  - Computed using start/end longitude and latitude.
  - Routing logic is offloaded to the OSRM API.
- Station usage
  - Total trip count by station name and station ID.
  - Arrivals and departures tracked per station.
- Actual vs optimal trip duration
  - Compare rider behavior against estimated optimal duration.
  - Used to evaluate:
    - Whether members keep bikes longer than casual riders.
    - Whether electric or classic bikes are favored for longer rides.

Visualizations Made:

- Histograms
  - Number of station uses by:
    - Bike type (classic/electric)
    - Rider type (member/casual)
- Scatter plots
  - Trip duration vs time of day
    - Highlights dense usage windows for member/casual riders.
  - Start longitude vs start latitude
    - Shows density/spread of trip origins, colored by rider type and bike type.
  - Start station vs end station (with ID jitter)
    - Visualizes station-to-station flow.
  - Start lng/lat vs end lng/lat
    - Shows approximate rider trip distances.

Conclusions to be Drawn:

- Does rider type (`member` vs `casual`) affect trip duration?
- Does bike type (`classic` vs `electric`) affect:
  - Station usage patterns?
  - Ride duration?

### **Storage**

PostgreSQL 18 database is being used to hold all the data.

- Avoiding duplicate code via SQLModel filling a dual role as ORM (SQLAlchemy) and API schema (Pydantic).
- Async operations via `postgresql+asyncpg` driver with `asyncpg` for session management.

## **API**

FastAPI with Uvicorn ASGI server for concurrent connections.

**Sample endpoints**:

- `GET /api` - root api route
- `GET /api/db/health` - db status
- `GET /api/engine/info` - info on asyncpg engine
- `GET /api/session/info` - async session info

## **Frontend**

React + Vite stack with data visualization components. The react app makes HTTP requests to FastAPI endpoints, receives JSON responses in turn.

## **Middleware**

- Nginx reverse proxy routes frontend requests to the FastAPI backend.

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
- ![React Router](https://img.shields.io/badge/React%20Router-CA4245?style=for-the-badge&logo=reactrouter&logoColor=white)
- ![TanStack Query](https://img.shields.io/badge/TanStack%20Query-FF4154?style=for-the-badge&logo=reactquery&logoColor=white)
- ![NodeJS](https://img.shields.io/badge/node.js-6DA55F?style=for-the-badge&logo=node.js&logoColor=white)

[^badgesSource]: badges from [Ileriayo/markdown-badges](https://github.com/Ileriayo/markdown-badges/tree/master)

[^gitignore]: Generated by [toptal](https://www.toptal.com/developers/gitignore/api)
