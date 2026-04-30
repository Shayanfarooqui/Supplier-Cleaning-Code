import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import pandas as pd
import shutil
import uuid
import pickle

# Import our processing logic
from processor import (
    read_file_safely, clean_chicken, clean_extra_uk, clean_zyrofisher, clean_ison,
    standardize_schema, apply_cross_supplier_rules, process_lightspeed_match
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
            print(f"[DEBUG Extra UK] Uploaded filename: {saved_paths['extra_uk']}")
            extra_df = read_file_safely(saved_paths['extra_uk'])
            print(f"[DEBUG Extra UK] Shape: {extra_df.shape}")
            print(f"[DEBUG Extra UK] Columns: {extra_df.columns.tolist()}")
            print(f"[DEBUG Extra UK] Brand sample: {extra_df['Brand'].head(3).tolist() if 'Brand' in extra_df.columns else 'NO BRAND COLUMN'}")
            extra_clean = clean_extra_uk(extra_df)
            print(f"[DEBUG Extra UK] After clean shape: {extra_clean.shape}")
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
        
        # 3. Standardize Schema
        std_chicken = standardize_schema(chicken_clean, 'Chicken')
        std_extra = standardize_schema(extra_clean, 'Extra UK')
        std_zyro = standardize_schema(zyro_clean, 'Zyrofisher')
        std_ison = standardize_schema(ison_clean, 'Ison')
        
        # 4. Cross-Supplier Rules
        allowed_items, banned_items = apply_cross_supplier_rules(std_chicken, std_extra, std_zyro, std_ison)
        
        # 5. Save intermediate state
        job_dir = os.path.join(RESULTS_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        with open(os.path.join(job_dir, "allowed.pkl"), "wb") as f:
            pickle.dump(allowed_items, f)
        with open(os.path.join(job_dir, "banned.pkl"), "wb") as f:
            pickle.dump(banned_items, f)
        with open(os.path.join(job_dir, "box_qty.pkl"), "wb") as f:
            pickle.dump(box_qty_df, f)
        
        # 6. Save cleaned data as downloadable CSV
        cleaned_file = "Cleaned_Suppliers.csv"
        allowed_items.to_csv(os.path.join(RESULTS_DIR, cleaned_file), index=False)
        
        # Save per-supplier cleaned CSVs for individual download
        supplier_cleaned_map = {
            'Chicken': chicken_clean,
            'Extra UK': extra_clean,
            'Zyrofisher': zyro_clean,
            'Ison': ison_clean
        }
        for supplier_name, supplier_df in supplier_cleaned_map.items():
            print(f"[DEBUG] {supplier_name}: type={type(supplier_df).__name__}, len={len(supplier_df)}, empty={supplier_df.empty}")
            if not supplier_df.empty:
                safe_name = supplier_name.replace(' ', '_')
                per_file = f"{safe_name}.csv"
                supplier_df.to_csv(os.path.join(RESULTS_DIR, per_file), index=False)
                analysis[supplier_name]['download'] = f"/api/download/{per_file}"
                print(f"[DEBUG] Saved {per_file}, download URL set")
        
        # Merge all cleaned supplier DataFrames into a single file
        merged_parts = [df for df in supplier_cleaned_map.values() if not df.empty]
        merged_download = None
        if merged_parts:
            merged_df = pd.concat(merged_parts, ignore_index=True)
            merged_file = "Merged_Cleaned.csv"
            merged_df.to_csv(os.path.join(RESULTS_DIR, merged_file), index=False)
            merged_download = f"/api/download/{merged_file}"
            print(f"[DEBUG] Saved merged file {merged_file} with {len(merged_df)} rows")
        
        print(f"[DEBUG] Final analysis: {analysis}")
        
        # Also save box qty if present
        box_qty_file = "BoxQty_Exceptions.csv"
        if not box_qty_df.empty:
            box_qty_df.to_csv(os.path.join(RESULTS_DIR, box_qty_file), index=False)
            
        return JSONResponse({
            "status": "success", 
            "message": "Supplier files processed successfully.",
            "job_id": job_id,
            "analysis": analysis,
            "downloads": {
                "cleaned": f"/api/download/{cleaned_file}",
                "merged": merged_download,
                "box_qty": f"/api/download/{box_qty_file}" if not box_qty_df.empty else None
            }
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
    try:
        job_dir = os.path.join(RESULTS_DIR, job_id)
        if not os.path.exists(job_dir):
            raise HTTPException(status_code=404, detail="Job ID not found or expired")
            
        # 1. Load intermediate DataFrames
        with open(os.path.join(job_dir, "allowed.pkl"), "rb") as f:
            allowed_items = pickle.load(f)
        with open(os.path.join(job_dir, "banned.pkl"), "rb") as f:
            banned_items = pickle.load(f)
        with open(os.path.join(job_dir, "box_qty.pkl"), "rb") as f:
            box_qty_df = pickle.load(f)
            
        # 2. Save Lightspeed temporarily
        temp_dir = os.path.join(tempfile.gettempdir(), f"ls_hub_{job_id}")
        os.makedirs(temp_dir, exist_ok=True)
        ls_path = os.path.join(temp_dir, lightspeed.filename)
        with open(ls_path, "wb") as buffer:
            shutil.copyfileobj(lightspeed.file, buffer)
            
        # 3. Read and compare
        ls_df = read_file_safely(ls_path)
        matched_df, new_skus_df, outliers_df = process_lightspeed_match(allowed_items, banned_items, ls_df)
        
        # 4. Save Outputs Final
        matched_file = "Matched_Items.csv"
        new_skus_file = "New_SKUs.csv"
        outliers_file = "Outliers.csv"
        box_qty_file = "BoxQty_Exceptions.csv"
        
        matched_df.to_csv(os.path.join(RESULTS_DIR, matched_file), index=False)
        new_skus_df.to_csv(os.path.join(RESULTS_DIR, new_skus_file), index=False)
        outliers_df.to_csv(os.path.join(RESULTS_DIR, outliers_file), index=False)
        box_qty_df.to_csv(os.path.join(RESULTS_DIR, box_qty_file), index=False)
        
        # Cleanup intermediate state if desired (commented out to safely let user download)
        # shutil.rmtree(job_dir, ignore_errors=True)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        return JSONResponse({
            "status": "success", 
            "message": "Comparison complete.",
            "downloads": {
                "matched": f"/api/download/{matched_file}",
                "new_skus": f"/api/download/{new_skus_file}",
                "outliers": f"/api/download/{outliers_file}",
                "box_qty": f"/api/download/{box_qty_file}"
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
