import pandas as pd
import os
import re

def read_file_safely(path):
    """
    Tries to read CSV or Excel files robustly, parsing all columns as strings initially 
    to prevent data loss (e.g., scientific notation on long barcodes).
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in ['.xlsx', '.xls']:
        return pd.read_excel(path, dtype=str)
    
    # Common encodings for Windows CSVs
    tried = []
    for enc in ["utf-8", "utf-8-sig", "windows-1252", "latin-1"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str)
        except Exception as e:
            tried.append(f"{enc}: {str(e)[:50]}")
            continue
            
    # As a last resort, try replacing bad bytes
    try:
        return pd.read_csv(path, encoding="windows-1252", encoding_errors="replace", dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read {path}. Errors: {tried}")

def clean_column_names(df):
    """
    Strips whitespace from column names to avoid annoying indexing key errors.
    """
    df.columns = df.columns.astype(str).str.strip()
    return df

def clean_chicken(info_df, cost_df):
    """
    Processes the Chicken files according to business rules.
    """
    info_df = clean_column_names(info_df)
    cost_df = clean_column_names(cost_df)
    
    # 1. Merge Files
    # We must find the common key. Usually "Product Code" or "SKU"
    # To make this robust, let's look for common columns.
    common_cols = set(info_df.columns).intersection(set(cost_df.columns))
    key_col = None
    for k in ["SKU", "Product Code", "ProductCode", "Item Code", "Barcode", "Product ID"]:
        # Case insensitive check
        info_match = [c for c in info_df.columns if c.lower() == k.lower()]
        cost_match = [c for c in cost_df.columns if c.lower() == k.lower()]
        if info_match and cost_match:
            key_col = info_match[0] # Use info's casing
            
            # Need to match cost's casing to info's casing
            cost_df = cost_df.rename(columns={cost_match[0]: key_col})
            break
            
    if not key_col and len(common_cols) > 0:
        key_col = list(common_cols)[0]
    
    if key_col:
        df = pd.merge(info_df, cost_df, on=key_col, how='left')
    else:
        # Fallback if no matching columns discovered, just use info_df (not ideal)
        df = info_df.copy()
        print("Warning: Could not find common key to merge Chicken Info and Cost files.")

    # Convert everything to standard string and remove NaNs for string ops
    df = df.fillna('')
    
    # Standardize our expected columns if they exist under different names
    # Let's map them to a temporary common namespace
    col_map = {
        'Category': ['Category', 'Product Category'],
        'Manufacturer': ['Manufacturer', 'Brand'],
        'Cost Price': ['Cost Price', 'Cost', 'Unit Cost'],
        'RRP': ['RRP', 'Retail Price', 'Retail']
    }
    
    def get_col(standard_name):
        for candidate in col_map.get(standard_name, [standard_name]):
            matches = [c for c in df.columns if c.lower() == candidate.lower()]
            if matches: return matches[0]
        return None

    cat_col = get_col('Category')
    mfg_col = get_col('Manufacturer')
    cost_col = get_col('Cost Price')
    rrp_col = get_col('RRP')
    
    # 2. Delete Unnecessary Columns
    # Remove "image" columns
    image_cols = [c for c in df.columns if "image" in c.lower()]
    df = df.drop(columns=image_cols)
    
    # Delete specific columns
    exact_drops = [
        "Master Product Name", "TXT Product Description", "Stock",
        "Brand + Product", "Commodity Code", "Country of Origin", "Filter Size 2"
    ]
    cols_to_drop = [c for c in df.columns if c in exact_drops or c.strip() in exact_drops]
    df = df.drop(columns=cols_to_drop)
    
    # 3. Filter Out Unwanted Items
    if cat_col:
        # Contains (case-insensitive)
        contains_drop = ["apparel", "nutrition", "groupsets"]
        mask_contains = df[cat_col].str.lower().apply(lambda x: any(drop in x for drop in contains_drop))
        
        # Exact (case-insensitive for safety, but data says exact)
        exact_drop_cats = ["Bikes & Frames", "Bikes", "E-Bikes", "Frames", "Bike Trailers"]
        mask_exact = df[cat_col].str.strip().str.lower().isin([x.lower() for x in exact_drop_cats])
        
        df = df[~(mask_contains | mask_exact)]
        
    if mfg_col:
        # Manufacturer Exact matches
        bad_mfgs = ["Ale Clothing", "Burley", "Cyclus Tools", "Datatag", "DMT Shoes", "Enervit", "Peruzzo", "Wera Tools"]
        mask_bad_mfg = df[mfg_col].str.strip().str.lower().isin([x.lower() for x in bad_mfgs])
        df = df[~mask_bad_mfg]
        
    if mfg_col and cat_col:
        # If Mfg in [KMC, Peruzzo, Cinelli] AND Cat is empty -> Drop
        target_mfgs = ["kmc", "peruzzo", "cinelli"]
        mask_target_mfg = df[mfg_col].str.strip().str.lower().isin(target_mfgs)
        mask_empty_cat = df[cat_col].str.strip() == ""
        df = df[~(mask_target_mfg & mask_empty_cat)]
        
    # By Invalid Pricing
    for price_col in [cost_col, rrp_col]:
        if price_col:
            # Drop if 0 or #N/A (already filled with '' mostly, but check original text '#N/A' or '0')
            # Since we did fillna(''), we must be careful. Actual 0 could be '0', '0.00'
            mask_zero = df[price_col].str.strip().isin(['0', '0.0', '0.00', '#N/A', '#n/a', 'NA'])
            df = df[~mask_zero]
            
    # 4. Fix Missing Category
    if mfg_col and cat_col:
        # If Mfg = Sapim and Cat is empty -> Spokes
        mask_sapim = df[mfg_col].str.strip().str.lower() == 'sapim'
        mask_empty_cat = df[cat_col].str.strip() == ""
        df.loc[mask_sapim & mask_empty_cat, cat_col] = "Spokes"
        
    # Basso bike and cinelli cost > 1000 -> drop
    if mfg_col and cost_col:
        mask_brand = df[mfg_col].str.strip().str.lower().isin(['basso bike', 'basso bikes', 'basso', 'cinelli'])
        
        # safely convert cost to float to check > 1000
        def safe_float(val):
            try:
                # Remove currency symbols and commas
                clean_val = re.sub(r'[^\d.]', '', str(val))
                return float(clean_val) if clean_val else 0.0
            except:
                return 0.0
                
        costs = df[cost_col].apply(safe_float)
        mask_expensive = costs > 1000
        
        df = df[~(mask_brand & mask_expensive)]
        
    df['Supplier'] = 'Chicken'
    return df

def clean_extra_uk(df):
    """
    Cleans Extra UK supplier data according to updated rules.
    
    Key: Category_Path contains real categories, NOT the Category column.
    Order: Apply row filters FIRST on Category_Path, THEN delete it.
    """
    df = clean_column_names(df)
    df = df.fillna('')
    
    print(f"[DEBUG Extra UK] Initial shape: {df.shape}")
    print(f"[DEBUG Extra UK] Columns: {df.columns.tolist()}")

    # Helper function to find column by candidate names
    def get_col(candidates):
        for c in df.columns:
            if c.lower().strip() in [x.lower() for x in candidates]:
                return c
        return None
    
    # Get column references BEFORE deleting anything
    cat_path_col = get_col(['Category_Path', 'Category Path'])
    brand_col = get_col(['Brand', 'Manufacturer', 'Product Brand'])
    barcode_col = get_col(['Barcode_1', 'Barcode', 'UPC', 'EAN', 'Bar Code'])
    cost_col = get_col(['Your_Price', 'Your Price', 'Cost', 'Cost Price', 'Unit Cost', 'Trade', 'QTrade'])
    rrp_col = get_col(['SRP', 'RRP', 'Retail', 'Price', 'Retail Price'])
    
    print(f"[DEBUG Extra UK] Column mapping - Category_Path: {cat_path_col}, Brand: {brand_col}, Barcode: {barcode_col}, Cost: {cost_col}, RRP: {rrp_col}")
    
    # APPLY ROW FILTERS FIRST (using Category_Path)
    
    # 1. Row Removal – Category Rules (using Category_Path)
    if cat_path_col:
        # Contains matches (case-insensitive)
        contains_cats = ["display", "tool", "bags", "backpacks", "apparel", "helmets", 
                         "shoe", "fizik spares", "insoles", "fizik misc"]
        
        print(f"[DEBUG Extra UK] Sample category_path values: {df[cat_path_col].unique()[:10].tolist()}")
        
        mask_contains = df[cat_path_col].astype(str).str.lower().str.contains('|'.join(contains_cats), regex=True, na=False)
        rows_to_remove_cat = mask_contains.sum()
        print(f"[DEBUG Extra UK] Category filtering: contains={mask_contains.sum()}, total_remove={rows_to_remove_cat}")
        df = df[~mask_contains]
        print(f"[DEBUG Extra UK] After category drop shape: {df.shape}")
    
    # 2. Row Removal – Brand Rules
    if brand_col:
        bad_brands = [
            "Bluegrass", "Chamois Butt'r", "Clif", "Delta", "Kids Ride Shotgun", 
            "MET", "Motorex", "Onguard", "Rockstop", "Squirt", "Veloforte", 
            "Moon Sport", "Orange Seal"
        ]
        mask_bad_brands = df[brand_col].astype(str).str.strip().str.lower().isin([x.lower() for x in bad_brands])
        rows_to_remove_brand = mask_bad_brands.sum()
        print(f"[DEBUG Extra UK] Brand filtering: {rows_to_remove_brand} rows to remove")
        df = df[~mask_bad_brands]
        print(f"[DEBUG Extra UK] After brand drop shape: {df.shape}")
    
    # 3. Row Removal – Barcode & Pricing Rules
    if barcode_col:
        mask_blank_barcode = df[barcode_col].astype(str).str.strip() == ''
        
        mask_invalid_price = pd.Series(False, index=df.index)
        for price_col in [cost_col, rrp_col]:
            if price_col:
                mask_invalid_price |= df[price_col].astype(str).str.strip().isin(['0', '0.0', '0.00', '#N/A', '#n/a', 'NA'])
        
        rows_to_remove_pricing = (mask_blank_barcode & mask_invalid_price).sum()
        print(f"[DEBUG Extra UK] Pricing filtering: blank_barcode={mask_blank_barcode.sum()}, invalid_price={mask_invalid_price.sum()}, both={rows_to_remove_pricing}")
        df = df[~(mask_blank_barcode & mask_invalid_price)]
        print(f"[DEBUG Extra UK] After pricing drop shape: {df.shape}")
    
    # NOW delete unwanted columns (AFTER all row filtering is done)
    # Clean Barcode_1: remove apostrophes
    barcode1_col = next((c for c in df.columns if c.strip().lower() == 'barcode_1'), None)
    if barcode1_col:
        df[barcode1_col] = df[barcode1_col].astype(str).str.replace("'", "").str.strip()
    
    # Drop specified unwanted columns
    cols_to_drop = []
    drop_candidates = [
        'account', 'category_path', 'barcode_2', 'assorted', 'currency',
        'each_2', 'qty_2', 'each_3', 'qty_3', 'each_4', 'qty_4',
        'order', 'box check', 'line total', 'filter size 2'
    ]
    for col in df.columns:
        if col.strip().lower() in drop_candidates:
            cols_to_drop.append(col)
    
    for col in df.columns:
        if col.startswith('Unnamed:') or col.strip() == '':
            if df[col].replace('', '0').astype(str).str.strip().eq('0').all():
                cols_to_drop.append(col)
    
    if cols_to_drop:
        print(f"[DEBUG Extra UK] Dropping columns: {cols_to_drop}")
        df = df.drop(columns=list(set(cols_to_drop)))
    
    print(f"[DEBUG Extra UK] After column drop shape: {df.shape}")
    
    df['Supplier'] = 'Extra UK'
    print(f"[DEBUG Extra UK] Final shape: {df.shape}")
    return df

def clean_zyrofisher(df):
    df = clean_column_names(df)
    df = df.fillna('')
    
    cols_to_drop = ["VatCode", "StockIndicator", "StockDueIn", "BriefDescription", 
                    "LongDescription", "ImageUrl", "OrangePrice", "BronzePrice", "SilverPrice"]
    df = df.drop(columns=[c for c in df.columns if c.strip() in cols_to_drop])
    
    cat_col = next((c for c in df.columns if c.lower() in ['category', 'product category']), None)
    brand_col = next((c for c in df.columns if c.lower() in ['brand', 'manufacturer']), None)
    
    if cat_col:
        bad_cats = ["Bags and Baskets", "BIKES", "Bottle Cages", "Bottles", "Car Racks", 
                    "Child Seats", "Child Transport Trailers", "Cleaners & Degreasers", 
                    "Cleaning Tools", "Clothing", "Cycling Computers and GPS", 
                    "Energy & Recovery Food & Drink", "Goggles", "Helmets", "Hydration Systems", 
                    "Lubes & Grease", "Map Holders", "Mirrors", "Phone & Accessory Mounts", 
                    "POS", "PROTECTION", "Pumps and CO2", "Puncture Protection", 
                    "Puncture Repair", "Racks", "Reflectors", "Shoes", "Sunglasses", 
                    "Toe Clips and Straps", "Tools", "Trainers and Rollers", 
                    "Travel/Storage Solutions", "Value Packs", "Workstands"]
        mask_cats = df[cat_col].str.strip().str.lower().isin([x.lower() for x in bad_cats])
        df = df[~mask_cats]
        
    if brand_col:
        bad_brands = ["Blackburn", "Bleedkit", "Bryton", "CatEye", "Cyclo", "EVOC", 
                      "Hamax", "Hiplok", "Joe's No Flats", "Leatt", "Minoura", "Mistral", 
                      "SIGG", "Time Sport", "UNIOR", "Weldtite", "Camelback", "Altura", "Giro"]
        mask_brands = df[brand_col].str.strip().str.lower().isin([x.lower() for x in bad_brands])
        df = df[~mask_brands]
        
    box_qty_col = next((c for c in df.columns if c.lower() in ['boxquantity', 'box qty']), None)
    box_qty_df = pd.DataFrame()
    if box_qty_col:
        mask_has_box = df[box_qty_col].str.strip() != ''
        box_qty_df = df[mask_has_box].copy()
        box_qty_df['Supplier'] = 'Zyrofisher (Box)'
        df = df[~mask_has_box]
        
    df['Supplier'] = 'Zyrofisher'
    return df, box_qty_df

def clean_ison(df):
    df = clean_column_names(df)
    df = df.fillna('')

    # Normalize em/en dashes to regular hyphens for robust matching
    def norm(s):
        return str(s).replace('–', '-').replace('—', '-').strip().lower()

    cat_col = next((c for c in df.columns if c.lower() in ['product category', 'category']), None)
    if cat_col:
        bad_cats = ["Bikes - Complete", "Clothing", "Frames", "Promotionals & POS",
                    "Protective Clothing & Helmets", "Scooters & Unicycles", "Skateboards",
                    "Tools", "Spokes & Nipples"]
        bad_cats_norm = {norm(x) for x in bad_cats}
        mask_cats = df[cat_col].apply(lambda x: norm(x) in bad_cats_norm)
        df = df[~mask_cats]

    # Handle Cost Price BEFORE dropping Trade
    qtrade_col = next((c for c in df.columns if c.lower() == 'qtrade'), None)
    trade_col = next((c for c in df.columns if c.lower() == 'trade'), None)

    if qtrade_col and trade_col:
        mask_qtrade_empty = df[qtrade_col].str.strip().isin(['', '0', '0.0', '0.00'])
        df['Cost Price'] = df[qtrade_col]
        df.loc[mask_qtrade_empty, 'Cost Price'] = df.loc[mask_qtrade_empty, trade_col]
    elif trade_col:
        df['Cost Price'] = df[trade_col]
    elif qtrade_col:
        df['Cost Price'] = df[qtrade_col]

    cols_to_drop = ["Date Updated", "Weight (g.)", "Approx Weight", "Pack", "MX", "Trade", "Qty",
                    "Web Description", "Trade Price (£)", "Trade Price (Ã‚Â£)",
                    "Quantity Break", "Manufacturer Part Code"]
    cols_to_drop_lower = {c.lower() for c in cols_to_drop}
    df = df.drop(columns=[c for c in df.columns if c.strip().lower() in cols_to_drop_lower])

    # Product Group rules
    pg_col = next((c for c in df.columns if c.lower() == 'product group'), None)
    if pg_col:
        # Remove any row whose Product Group contains "discontinued" or "cycle computers"
        mask_discontinued = df[pg_col].str.lower().str.contains('discontinued', na=False)
        mask_cycle_computers = df[pg_col].str.lower().str.contains('cycle computers', na=False)
        df = df[~(mask_discontinued | mask_cycle_computers)]

        bad_pgs = [
            "Bags - Bikepacking", "Bags - Discontinued", "Bags - Frame", "Bags - Handlebar",
            "Bags - Other", "Bags - Panniers", "Bags - Rack Packs", "Bags - Saddle",
            "Baskets", "Bells",
            "Carriers - Discontinued", "Chain Accessories - Discontinued", "Chain Devices - Discontinued",
            "Cycle Storage", "Discontinued Lines",
            "Forks - MTB & BMX - Discontinued", "Forks - Road & Hybrid - Discontinued",
            "Forks Spares - Discontinued", "Gears - Rear - Discontinued",
            "GPS & Phone Holders & Mounts", "Grips - MTB - Discontinued", "Hardware",
            "Hub Spares - Discontinued", "Lights - Battery", "Lights - Dynamo",
            "Lights - e-Bike", "Lights - Rechargeable", "Lights - Spares",
            "Locks - Cable", "Locks - Chain", "Locks - Home Security", "Locks - Shackle D-Type",
            "Locks & Security - Discontinued", "Luggage Rack Spares", "Luggage Racks - Front",
            "Luggage Racks - Rear", "Mirrors", "Multi Tools", "Number Plates - BMX",
            "Personal Care", "Pumps", "Puncture Repair", "Puncture Repair - Discontinued",
            "Reflective & Safety", "Reflectors", "Rims - 700c & 29\" - Discontinued",
            "Shop Supplies", "Stunt Pegs - BMX", "Stunt Pegs - BMX - Discontinued",
            "Trailer Spares", "Trailers", "Turbo & Home Trainers", "Water Bottle Cages",
            "Water Bottles", "Water Bottles - Discontinued", "Water Carriers & Hydration Packs - Spares"
        ]
        bad_pgs_norm = {norm(x) for x in bad_pgs}
        mask_bad_pgs = df[pg_col].apply(lambda x: norm(x) in bad_pgs_norm)
        df = df[~mask_bad_pgs]

    # Exclude by Keyword 'Bag'
    name_col = next((c for c in df.columns if c.lower() in ['product name', 'name', 'title']), None)
    desc_col = next((c for c in df.columns if c.lower() in ['description', 'product description']), None)

    if name_col:
        mask_bag_name = df[name_col].str.lower().str.contains(r'\bbag\b', regex=True, na=False)
        df = df[~mask_bag_name]
    if desc_col:
        mask_bag_desc = df[desc_col].str.lower().str.contains(r'\bbag\b', regex=True, na=False)
        df = df[~mask_bag_desc]

    # Exclude by Brand
    brand_col = next((c for c in df.columns if c.lower() in ['product brand', 'brand', 'manufacturer']), None)
    if brand_col:
        bad_brands = ["Fidlock", "Cyclo", "Mucky Nutz", "Schwalbe", "Impac", "Draper", "Squire", "Happy Bottom"]
        mask_bad_brands = df[brand_col].str.strip().str.lower().isin([x.lower() for x in bad_brands])
        df = df[~mask_bad_brands]

    # De-duplicate name by replacing color/weight/size
    color_col = next((c for c in df.columns if c.lower() == 'color'), None)
    weight_col = next((c for c in df.columns if c.lower() in ['weight', 'weight (g.)', 'approx weight']), None)
    size_col = next((c for c in df.columns if c.lower() == 'size'), None)
    part_col = next((c for c in df.columns if c.lower() in ['our part no', 'part no', 'part number']), None)
    
    if name_col:
        def clean_name(row):
            n = str(row[name_col])
            for col in [color_col, weight_col, size_col, part_col]:
                if col and str(row[col]).strip() != '':
                    val = str(row[col]).strip()
                    try:
                        n = re.sub(re.escape(val), '', n, flags=re.IGNORECASE)
                    except:
                        pass
            return re.sub(r'\s+', ' ', n).strip()
            
        df[name_col] = df.apply(clean_name, axis=1)

    df['Supplier'] = 'Ison'
    return df

def standardize_schema(df, supplier_name):
    """
    Standardize the cleaned supplier dataframe into the final 19-column Lightspeed schema.
    """
    column_mapping = {
        'UPC': ['UPC', 'EAN', 'Barcode', 'Bar Code'],
        'EAN': ['EAN', 'UPC', 'Barcode', 'Bar Code'], # Usually EAN and UPC are in same column
        'Custom SKU': ['SKU', 'Stock Code', 'Stock_Code', 'Product Code', 'Item Code', 'Part No', 'Part Number', 'Our Part No', 'Code'],
        'Description': ['Description', 'Name', 'Title', 'Product Name', 'Item Name'],
        'Brand': ['Brand', 'Manufacturer', 'Product Brand'],
        'Category': ['Category', 'Product Category', 'Web Category'],
        'Default Cost': ['Cost', 'Cost Price', 'Unit Cost', 'Trade', 'QTrade'],
        'Price': ['RRP', 'Retail', 'Price', 'Retail Price'],
        'Default Vendor ID': ['Vendor ID', 'Supplier ID', 'Supplier Code', 'SKU', 'Product Code']
    }
    
    final_cols = [
        'System ID', 'UPC', 'EAN', 'Custom SKU', 'Manufacturer SKU', 
        'Default Vendor ID', 'Description', 'Default Vendor', 'Item Type', 
        'Tax Class', 'Brand', 'Top Level Category', 'Default Cost', 
        'Price', 'Archived (Yes / No)', 'Category', 'Quantity on Hand', 
        'Lifetime Quantity Sold', '# of Sales'
    ]
    
    std_df = pd.DataFrame(columns=final_cols)
    
    if df.empty:
        return std_df
        
    for std_col, candidates in column_mapping.items():
        # Find the first matching column in the df
        for cand in candidates:
            match = [c for c in df.columns if c.lower() == cand.lower()]
            if match:
                std_df[std_col] = df[match[0]]
                break
                
    std_df['Default Vendor'] = supplier_name
    
    # Fill remaining columns with empty strings
    std_df = std_df.fillna('')

    # Prevent scientific notation and decimals for barcodes when exported to CSV
    for col in ['UPC', 'EAN']:
        if col in std_df.columns:
            def fix_barcode(val):
                val = str(val).strip()
                if not val or val.lower() in ['nan', 'none', 'null']:
                    return ''
                try:
                    # If it looks like a float or scientific notation (e.g. 1.23E+12 or 123456.0)
                    if 'e' in val.lower() or '.' in val:
                        # Format as an exact integer string
                        return f"{float(val):.0f}"
                except ValueError:
                    pass
                return val
            std_df[col] = std_df[col].apply(fix_barcode)

    return std_df

def apply_cross_supplier_rules(chicken_df, extra_df, zyro_df, ison_df):
    """
    Merges all supplier dataframes and applies cross-supplier sourcing constraints.
    Returns the allowed items list and the banned items list (for potential stock merging).
    """
    combined = pd.concat([chicken_df, extra_df, zyro_df, ison_df], ignore_index=True)
    
    banned_mask = pd.Series(False, index=combined.index)
    
    brand_s = combined['Brand'].str.strip().str.lower()
    vendor_s = combined['Default Vendor']
    
    # KMC: Chicken only
    banned_mask |= (brand_s == 'kmc') & (vendor_s != 'Chicken')
    
    # Schwalbe & Impac: Not Ison
    banned_mask |= (brand_s.isin(['schwalbe', 'impac'])) & (vendor_s == 'Ison')
    
    # Clarks: Not Zyro Fisher
    banned_mask |= (brand_s == 'clarks') & (vendor_s == 'Zyrofisher')
    
    # SRAM & Selle Italia: Zyro only
    banned_mask |= (brand_s.isin(['sram', 'selle italia'])) & (vendor_s != 'Zyrofisher')
    
    allowed = combined[~banned_mask].copy()
    banned = combined[banned_mask].copy()
    
    return allowed, banned

def process_lightspeed_match(allowed_df, banned_df, ls_df):
    """
    Compares cleaned items against the Lightspeed extract.
    - Categorizes into Matched, Outliers, New SKUs.
    - Handles Vendor ID merging for banned items with physical stock.
    """
    ls_df = clean_column_names(ls_df).fillna('')
    
    # Ensure LS has UPC and stock info
    ls_upc_col = next((c for c in ls_df.columns if c.lower() in ['upc', 'ean', 'barcode']), None)
    ls_stock_col = next((c for c in ls_df.columns if 'quantity' in c.lower() or 'stock' in c.lower() or 'on hand' in c.lower()), None)
    
    if not ls_upc_col:
        print("Warning: Could not find matching UPC column in Lightspeed. Assuming all are New SKUs.")
        return pd.DataFrame(columns=allowed_df.columns), allowed_df.copy(), pd.DataFrame(columns=allowed_df.columns)
        
    # Clean UPCs for matching
    allowed_df['Match_UPC'] = allowed_df['UPC'].astype(str).str.strip().str.lstrip('0')
    banned_df['Match_UPC'] = banned_df['UPC'].astype(str).str.strip().str.lstrip('0')
    ls_df['Match_UPC'] = ls_df[ls_upc_col].astype(str).str.strip().str.lstrip('0')
    
    # 1. Vendor ID Merging for Banned items with Stock
    if ls_stock_col and not banned_df.empty:
        # Check which banned items are in LS AND have stock > 0
        def safe_float(v):
            try: return float(v)
            except: return 0.0
            
        ls_stock = ls_df.set_index('Match_UPC')[ls_stock_col].apply(safe_float)
        
        for idx, banned_row in banned_df.iterrows():
            upc = banned_row['Match_UPC']
            if upc and upc in ls_stock.index and ls_stock[upc] > 0:
                # Find the corresponding allowed item
                allowed_match = allowed_df[allowed_df['Match_UPC'] == upc]
                if not allowed_match.empty:
                    # Append undesired Vendor ID to Manufacturer SKU
                    target_idx = allowed_match.index[0]
                    existing_sku = str(allowed_df.loc[target_idx, 'Manufacturer SKU'])
                    undesired_vid = str(banned_row['Default Vendor ID'])
                    if undesired_vid and undesired_vid not in existing_sku:
                        if existing_sku:
                            allowed_df.loc[target_idx, 'Manufacturer SKU'] = existing_sku + ',' + undesired_vid
                        else:
                            allowed_df.loc[target_idx, 'Manufacturer SKU'] = undesired_vid

    # 2. Categorize Results Map
    matched_mask = allowed_df['Match_UPC'].isin(ls_df['Match_UPC']) & (allowed_df['Match_UPC'] != '')
    
    matched_df = allowed_df[matched_mask].copy()
    non_matched_df = allowed_df[~matched_mask].copy()
    
    # Drop temp Match_UPC
    matched_df = matched_df.drop(columns=['Match_UPC'])
    non_matched_df = non_matched_df.drop(columns=['Match_UPC'])
    
    # For now, put all non_matched into New_SKUs. We can refine logic for Outliers if needed.
    # Often, Outliers are ones that have UPC but no match, or blank UPC.
    mask_blank_upc = non_matched_df['UPC'].str.strip() == ''
    outliers_df = non_matched_df[mask_blank_upc].copy()
    new_skus_df = non_matched_df[~mask_blank_upc].copy()

    return matched_df, new_skus_df, outliers_df
