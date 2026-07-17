import os
import tempfile
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import pandas as pd
import shutil
import uuid

from processor import read_file_safely, clean_chicken

app = FastAPI(title="Chicken Supplier Cleaning API")

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

@app.post("/api/clean")
async def clean_chicken_files(
    chicken_info: UploadFile = File(None),
    chicken_cost: UploadFile = File(None)
):
    job_id = str(uuid.uuid4())
    temp_dir = os.path.join(tempfile.gettempdir(), f"chicken_clean_{job_id}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        saved_paths = {}
        if chicken_info and getattr(chicken_info, "filename", None):
            info_path = os.path.join(temp_dir, chicken_info.filename)
            with open(info_path, "wb") as buffer:
                shutil.copyfileobj(chicken_info.file, buffer)
            saved_paths['chicken_info'] = info_path

        if chicken_cost and getattr(chicken_cost, "filename", None):
            cost_path = os.path.join(temp_dir, chicken_cost.filename)
            with open(cost_path, "wb") as buffer:
                shutil.copyfileobj(chicken_cost.file, buffer)
            saved_paths['chicken_cost'] = cost_path

        if not saved_paths:
            return JSONResponse({"status": "error", "message": "No files uploaded"}, status_code=400)

        c_info_df = read_file_safely(saved_paths['chicken_info']) if 'chicken_info' in saved_paths else pd.DataFrame()
        c_cost_df = read_file_safely(saved_paths['chicken_cost']) if 'chicken_cost' in saved_paths else pd.DataFrame()

        if c_info_df.empty and c_cost_df.empty:
            return JSONResponse({"status": "error", "message": "No data in files"}, status_code=400)

        print("[DEBUG] Starting clean_chicken...")
        try:
            chicken_clean, removed_items, stats = clean_chicken(c_info_df, c_cost_df)
            print("[DEBUG] clean_chicken completed successfully")
        except Exception as e:
            import traceback
            print("[ERROR] clean_chicken failed:")
            print(traceback.format_exc())
            raise

        if chicken_clean.empty:
            return JSONResponse({"status": "error", "message": "No data after cleaning"}, status_code=400)

        # Save cleaned file
        output_file = "Chicken_Cleaned.csv"
        output_path = os.path.join(RESULTS_DIR, output_file)
        chicken_clean.to_csv(output_path, index=False)

        # Save removed items file
        removed_file = "Chicken_Removed_Items.csv"
        removed_path = os.path.join(RESULTS_DIR, removed_file)
        if not removed_items.empty:
            removed_items.to_csv(removed_path, index=False)

        downloads = {
            "cleaned": f"/api/download/{output_file}"
        }
        if not removed_items.empty:
            downloads["removed"] = f"/api/download/{removed_file}"

        return JSONResponse({
            "status": "success",
            "message": "Files cleaned successfully",
            "job_id": job_id,
            "insights": {
                "info_file_rows": int(stats.get('info_file_rows', 0)),
                "cost_file_rows": int(stats.get('cost_file_rows', 0)),
                "matched_with_price": int(stats.get('matched_with_price', 0)),
                "missing_vital_info": int(stats.get('missing_vital_info', 0)),
                "removed_rows": int(stats.get('removed_rows', 0))
            },
            "before_rows": int(len(c_info_df)),
            "after_rows": int(len(chicken_clean)),
            "download": f"/api/download/{output_file}",
            "downloads": downloads
        })
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(error_trace)
        return JSONResponse({
            "status": "error",
            "message": f"Error: {str(e)}",
            "detail": error_trace
        }, status_code=500)
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
