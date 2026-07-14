import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import pandas as pd
import shutil
import uuid

# Import our processing logic
from processor import (
    read_file_safely, clean_chicken, clean_extra_uk, clean_zyrofisher, clean_ison
)

app = FastAPI(title="Supplier Cleaning API")

# Setup static directory for frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

@app.get("/api/download/{filename}")
def download_file(filename: str):
    file_path = os.path.join(RESULTS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename, media_type='text/csv')
    return JSONResponse({"status": "error", "message": "File not found"}, status_code=404)

@app.post("/api/clean_suppliers")
async def clean_suppliers(
    chicken_info: UploadFile = File(None),
    chicken_cost: UploadFile = File(None),
    extra_uk: UploadFile = File(None),
    zyrofisher: UploadFile = File(None),
    ison: UploadFile = File(None)
):
    job_id = str(uuid.uuid4())
    temp_dir = os.path.join(tempfile.gettempdir(), f"supplier_hub_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        # 1. Save all uploads to temp dir to preserve extensions
        files_map = {
            'chicken_info': chicken_info,
            'chicken_cost': chicken_cost,
            'extra_uk': extra_uk,
            'zyrofisher': zyrofisher,
            'ison': ison
        }
        
        saved_paths = {}
        for key, f in files_map.items():
            if f is not None and getattr(f, "filename", None):
                path = os.path.join(temp_dir, f.filename)
                with open(path, "wb") as buffer:
                    shutil.copyfileobj(f.file, buffer)
                saved_paths[key] = path
            
        analysis = {}

        # 2. Ingest and Clean
        c_info_df = read_file_safely(saved_paths['chicken_info']) if 'chicken_info' in saved_paths else pd.DataFrame()
        c_cost_df = read_file_safely(saved_paths['chicken_cost']) if 'chicken_cost' in saved_paths else pd.DataFrame()
        chicken_clean = clean_chicken(c_info_df, c_cost_df) if not c_info_df.empty or not c_cost_df.empty else pd.DataFrame()
        analysis['Chicken'] = {'before': len(c_info_df), 'after': len(chicken_clean), 'download': None}
        
        extra_clean = pd.DataFrame()
        if 'extra_uk' in saved_paths:
            extra_df = read_file_safely(saved_paths['extra_uk'])
            extra_clean = clean_extra_uk(extra_df)
            analysis['Extra UK'] = {'before': len(extra_df), 'after': len(extra_clean), 'download': None}
        else:
            analysis['Extra UK'] = {'before': 0, 'after': 0, 'download': None}
        
        zyro_clean = pd.DataFrame()
        box_qty_df = pd.DataFrame()
        if 'zyrofisher' in saved_paths:
            zyro_df = read_file_safely(saved_paths['zyrofisher'])
            zyro_clean, box_qty_df = clean_zyrofisher(zyro_df)
            analysis['Zyrofisher'] = {'before': len(zyro_df), 'after': len(zyro_clean), 'download': None}
        else:
            analysis['Zyrofisher'] = {'before': 0, 'after': 0, 'download': None}
        
        ison_clean = pd.DataFrame()
        if 'ison' in saved_paths:
            ison_df = read_file_safely(saved_paths['ison'])
            ison_clean = clean_ison(ison_df)
            analysis['Ison'] = {'before': len(ison_df), 'after': len(ison_clean), 'download': None}
        else:
            analysis['Ison'] = {'before': 0, 'after': 0, 'download': None}
        
        # 3. Save cleaned supplier outputs
        supplier_cleaned_map = {
            'Chicken': chicken_clean,
            'Extra UK': extra_clean,
            'Zyrofisher': zyro_clean,
            'Ison': ison_clean
        }

        downloads = {}
        for supplier_name, supplier_df in supplier_cleaned_map.items():
            if not supplier_df.empty:
                safe_name = supplier_name.replace(' ', '_')
                per_file = f"{safe_name}.csv"
                supplier_df.to_csv(os.path.join(RESULTS_DIR, per_file), index=False)
                analysis[supplier_name]['download'] = f"/api/download/{per_file}"
                downloads[supplier_name] = f"/api/download/{per_file}"

        box_qty_file = None
        if not box_qty_df.empty:
            box_qty_file = "BoxQty_Exceptions.csv"
            box_qty_df.to_csv(os.path.join(RESULTS_DIR, box_qty_file), index=False)
            downloads['BoxQty_Exceptions'] = f"/api/download/{box_qty_file}"

        return JSONResponse({
            "status": "success",
            "message": "Supplier files processed successfully.",
            "job_id": job_id,
            "analysis": analysis,
            "downloads": downloads
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    finally:
        # Cleanup temp dir
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

@app.post("/api/compare_lightspeed")
async def compare_lightspeed(
    job_id: str = Form(...),
    lightspeed: UploadFile = File(...)
):
    return JSONResponse({
        "status": "error",
        "message": "Lightspeed comparison is disabled until intermediate result storage is restored."
    }, status_code=501)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
