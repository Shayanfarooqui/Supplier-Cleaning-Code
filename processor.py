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
    Returns: (cleaned_df, removed_df, stats)
    """
    info_df = clean_column_names(info_df)
    cost_df = clean_column_names(cost_df)

    print(f"[DEBUG] Info columns: {info_df.columns.tolist()}")
    print(f"[DEBUG] Cost columns: {cost_df.columns.tolist()}")

    stats = {}
    all_removed = pd.DataFrame()
    original_info_rows = len(info_df)

    # 1. Merge Files
    common_cols = set(info_df.columns).intersection(set(cost_df.columns))
    print(f"[DEBUG] Common columns: {list(common_cols)}")
    key_col = None
    for k in ["SKU", "Product Code", "ProductCode", "Item Code", "Code", "Barcode", "Product ID"]:
        info_match = [c for c in info_df.columns if c.lower() == k.lower()]
        cost_match = [c for c in cost_df.columns if c.lower() == k.lower()]
        if info_match and cost_match:
            key_col = info_match[0]
            print(f"[DEBUG] Found key column: {key_col}")
            if cost_match[0] != key_col:
                cost_df = cost_df.rename(columns={cost_match[0]: key_col})
            break

    if not key_col and len(common_cols) > 0:
        key_col = list(common_cols)[0]
        print(f"[DEBUG] Using common column as key: {key_col}")

    if key_col:
        # Keep only relevant columns from cost_df (drop RRP since it's already in info)
        # Always include the key column for merging
        relevant_cols = ['Trade', 'Your Price', 'Cost', 'Unit Cost']
        cost_cols_to_keep = [c for c in cost_df.columns if c.lower() in [x.lower() for x in relevant_cols] or c.lower() == key_col.lower()]

        if not cost_cols_to_keep:  # Fallback: keep all non-RRP columns
            cost_cols_to_keep = [c for c in cost_df.columns if c.lower() != 'rrp']

        cost_df_subset = cost_df[cost_cols_to_keep].copy()
        print(f"[DEBUG] Cost columns to keep: {cost_cols_to_keep}")

        # Merge on key column
        df = pd.merge(info_df, cost_df_subset, on=key_col, how='left')
        print(f"[DEBUG] Merged dataframe columns: {df.columns.tolist()}")

        # Count matches by checking Trade or Your Price columns
        match_cols = [c for c in df.columns if c.lower() in ['trade', 'your price']]
        if match_cols:
            try:
                stats['matched_with_price'] = int((df[match_cols[0]].astype(str).str.strip() != '').sum())
                print(f"[DEBUG] Matched with price: {stats['matched_with_price']}")
            except Exception as e:
                print(f"[DEBUG] Error counting matches: {e}")
                stats['matched_with_price'] = 0
        else:
            stats['matched_with_price'] = len(df)
    else:
        df = info_df.copy()
        stats['matched_with_price'] = 0
        print("Warning: Could not find common key to merge Chicken Info and Cost files.")

    df = df.fillna('')

    # Column mapping
    col_map = {
        'Category': ['Category', 'Product Category'],
        'Manufacturer': ['Manufacturer', 'Brand', 'Manf Code'],
        'Cost Price': ['Cost Price', 'Cost', 'Unit Cost', 'Trade', 'Your Price'],
        'RRP': ['RRP', 'Retail Price', 'Retail'],
        'Barcode': ['Barcode', 'UPC', 'EAN'],
        'Name': ['Name', 'Product Name', 'Title', 'Description', 'Variant Name']
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
    barcode_col = get_col('Barcode')
    name_col = get_col('Name')

    # 2. Delete Unnecessary Columns
    image_cols = [c for c in df.columns if "image" in c.lower()]
    df = df.drop(columns=image_cols)

    exact_drops = [
        "Master Product Name", "TXT Product Description", "Stock",
        "Brand + Product", "Commodity Code", "Country of Origin", "Filter Size 2"
    ]
    cols_to_drop = [c for c in df.columns if c in exact_drops or c.strip() in exact_drops]
    df = df.drop(columns=cols_to_drop)

    # Track vital info for stats
    vital_fields = []
    if barcode_col:
        vital_fields.append(('barcode', barcode_col))
    if name_col:
        vital_fields.append(('name', name_col))
    if mfg_col:
        vital_fields.append(('manufacturer', mfg_col))
    if cat_col:
        vital_fields.append(('category', cat_col))

    # Count rows with missing vital info
    missing_vital = 0
    for field_name, col in vital_fields:
        try:
            missing_vital += (df[col].astype(str).str.strip() == '').sum()
        except Exception as e:
            print(f"Error counting missing {field_name}: {e}")

    stats['missing_vital_info'] = missing_vital

    # 3. Filter Out Unwanted Items
    removal_mask = pd.Series(False, index=df.index)
    removal_reason = pd.Series('', index=df.index)

    def add_removals(mask, reason):
        new = mask & ~removal_mask
        removal_reason[new] = reason
        return removal_mask | mask

    # Category filters
    if cat_col:
        contains_drop = ["apparel", "nutrition", "groupsets"]
        mask_contains = df[cat_col].str.lower().apply(lambda x: any(drop in x for drop in contains_drop))
        removal_mask = add_removals(mask_contains, 'Category contains apparel/nutrition/groupsets')
        # Category is a combination of sub-categories, so match on contains rather than exact
        drop_cats = ["Bikes & Frames", "Bikes", "E-Bikes", "Frames", "Bike Trailers",
                     "Frame Bags", "Bottles", "Bottle Cages", "Protection"]
        cat_lower = df[cat_col].str.lower()
        for drop_cat in drop_cats:
            mask_drop_cat = cat_lower.str.contains(drop_cat.lower(), regex=False, na=False)
            removal_mask = add_removals(mask_drop_cat, f'Category contains "{drop_cat}"')

    # Manufacturer filters - including NEW rules
    if mfg_col:
        bad_mfgs = ["Ale Clothing", "Burley", "Cyclus Tools", "Datatag", "DMT Shoes", "Enervit", "Peruzzo", "Wera Tools"]
        mask_bad_mfg = df[mfg_col].str.strip().str.lower().isin([x.lower() for x in bad_mfgs])
        removal_mask = add_removals(mask_bad_mfg, 'Manufacturer removed')

    # Mfg/Category empty combo filter
    if mfg_col and cat_col:
        target_mfgs = ["kmc", "peruzzo", "cinelli"]
        mask_target_mfg = df[mfg_col].str.strip().str.lower().isin(target_mfgs)
        mask_empty_cat = df[cat_col].str.strip() == ""
        removal_mask = add_removals(mask_target_mfg & mask_empty_cat, 'Manufacturer with empty category')

    # Price filters - including NEW rules (>= 1000)
    def safe_float(val):
        try:
            clean_val = re.sub(r'[^\d.]', '', str(val))
            return float(clean_val) if clean_val else 0.0
        except:
            return 0.0

    for price_col in [cost_col, rrp_col]:
        if price_col:
            mask_zero = df[price_col].str.strip().isin(['0', '0.0', '0.00', '#N/A', '#n/a', 'NA'])
            removal_mask = add_removals(mask_zero, f'Zero or N/A price ({price_col})')

            # NEW: Remove if price >= 1000
            prices = df[price_col].apply(safe_float)
            mask_expensive = prices >= 1000
            removal_mask = add_removals(mask_expensive, f'Price >= 1000 ({price_col})')

    # Store removed items
    all_removed = df[removal_mask].copy()
    all_removed['Removal Reason'] = removal_reason[removal_mask]

    # Remove filtered items
    df = df[~removal_mask]

    # 4. Fix Missing Category
    if mfg_col and cat_col:
        mask_sapim = df[mfg_col].str.strip().str.lower() == 'sapim'
        mask_empty_cat = df[cat_col].str.strip() == ""
        df.loc[mask_sapim & mask_empty_cat, cat_col] = "Spokes"

    stats['info_file_rows'] = original_info_rows
    stats['cost_file_rows'] = len(cost_df)
    stats['removed_rows'] = len(all_removed)

    df['Supplier'] = 'Chicken'
    all_removed['Supplier'] = 'Chicken (Removed)'

    return df, all_removed, stats


ISON_REMOVE_BRANDS = [
    "Fidlock", "Cyclo", "Mucky Nutz", "Schwalbe", "Impac", "Draper", "Squire", "Happy Bottom"
]

ISON_REMOVE_CATEGORIES = [
    "Bikes - Complete", "Clothing", "Frames", "Promotionals & POS",
    "Protective Clothing & Helmets", "Scooters & Unicycles", "Skateboards",
    "Tools", "Spokes & Nipples"
]

ISON_REMOVE_GROUPS = [
    "Bags - Bikepacking", "Bags - Discontinued", "Bags - Frame", "Bags - Handlebar",
    "Bags - Other", "Bags - Panniers", "Bags - Rack Packs", "Bags - Saddle",
    "Baskets", "Bells",
    "Bottom Brackets - Miscellaneous - Discontinued", "Bottom Brackets - Sealed - Discontinued",
    "Brake Pads - Rim Brake - Discontinued", "Carriers - Discontinued",
    "Chain Accessories - Discontinued", "Chain Devices - Discontinued",
    "Cycle Computers - Discontinued", "Cycle Computers - Spares", "Cycle Storage",
    "Discontinued Lines",
    "Forks - MTB & BMX - Discontinued", "Forks - Road & Hybrid - Discontinued",
    "Forks Spares - Discontinued", "Gears - Rear - Discontinued",
    "GPS & Phone Holders & Mounts", "Grips - MTB - Discontinued", "Hardware",
    "Hub Spares - Discontinued",
    "Lights - Battery", "Lights - Dynamo", "Lights - e-Bike", "Lights - Rechargeable",
    "Lights - Spares",
    "Locks - Cable", "Locks - Chain", "Locks - Home Security", "Locks - Shackle D-Type",
    "Locks & Security - Discontinued",
    "Luggage Rack Spares", "Luggage Racks - Front", "Luggage Racks - Rear",
    "Mirrors", "Multi Tools", "Number Plates - BMX", "Personal Care",
    "Pumps", "Puncture Repair", "Puncture Repair - Discontinued",
    "Reflective & Safety", "Reflectors",
    'Rims - 700c & 29" - Discontinued', "Shop Supplies",
    "Stunt Pegs - BMX", "Stunt Pegs - BMX - Discontinued",
    "Trailer Spares", "Trailers", "Turbo & Home Trainers",
    "Water Bottle Cages", "Water Bottles", "Water Bottles - Discontinued",
    "Water Carriers & Hydration Packs - Spares"
]

ISON_DROP_COLUMNS = [
    "Date Updated", "Approx Weight", "Pack", "MX", "Trade", "Web Description", "Unit",
    "DDLU", "Weight (g.)", "Note", "Q note", "Q Trade", "Qty"
]

def _normalize_dashes(val):
    """Normalizes en/em dashes to plain hyphens so rule lists match real data."""
    return str(val).replace("–", "-").replace("—", "-").strip()

def clean_ison(df):
    """
    Cleans Ison supplier data. Rules are applied in order, matching is
    case-sensitive; en/em dashes are treated the same as hyphens.
    Returns: (cleaned_df, removed_df, stats)
    """
    df = clean_column_names(df)
    df = df.fillna('')

    stats = {'info_file_rows': len(df)}

    def get_col(name):
        matches = [c for c in df.columns if c.lower() == name.lower()]
        return matches[0] if matches else None

    brand_col = get_col('Product Brand')
    group_col = get_col('Product Group')
    cat_col = get_col('Product Category')

    removal_mask = pd.Series(False, index=df.index)
    removal_reason = pd.Series('', index=df.index)

    def add_removals(mask, reason):
        new = mask & ~removal_mask
        removal_reason[new] = reason
        return removal_mask | mask

    # 1. Remove items by Product Brand (exact match)
    if brand_col:
        brands = df[brand_col].map(_normalize_dashes)
        removal_mask = add_removals(brands.isin([_normalize_dashes(b) for b in ISON_REMOVE_BRANDS]), 'Brand removed')

    # 2. Remove discontinued products (Product Group contains "Discontinued")
    if group_col:
        removal_mask = add_removals(df[group_col].astype(str).str.contains('Discontinued', case=True, na=False), 'Discontinued product group')

    # 3. Remove items by Product Category (exact match)
    if cat_col:
        cats = df[cat_col].map(_normalize_dashes)
        removal_mask = add_removals(cats.isin([_normalize_dashes(c) for c in ISON_REMOVE_CATEGORIES]), 'Category removed')

    # 4. Remove items by Product Group (exact match)
    if group_col:
        groups = df[group_col].map(_normalize_dashes)
        removal_mask = add_removals(groups.isin([_normalize_dashes(g) for g in ISON_REMOVE_GROUPS]), 'Product group removed')

    all_removed = df[removal_mask].copy()
    all_removed['Removal Reason'] = removal_reason[removal_mask]
    df = df[~removal_mask].copy()

    # 5. Cost Price: use Q Trade when present, otherwise fall back to Trade
    trade_col = get_col('Trade')
    q_trade_col = get_col('Q Trade')
    if trade_col or q_trade_col:
        trade = df[trade_col].astype(str).str.strip() if trade_col else pd.Series('', index=df.index)
        q_trade = df[q_trade_col].astype(str).str.strip() if q_trade_col else pd.Series('', index=df.index)
        df['Cost Price'] = q_trade.where(q_trade != '', trade)

    # 6. Delete columns if they exist (Trade / Q Trade are dropped in favour of Cost Price)
    cols_to_drop = [c for c in df.columns if c in ISON_DROP_COLUMNS]
    df = df.drop(columns=cols_to_drop)

    stats['removed_rows'] = len(all_removed)
    stats['dropped_columns'] = cols_to_drop

    df['Supplier'] = 'Ison'
    all_removed['Supplier'] = 'Ison (Removed)'

    return df, all_removed, stats


ZYRO_REMOVE_BRANDS = [
    "Blackburn", "Bleedkit", "Bryton", "CatEye", "Cyclo", "EVOC", "Hamax",
    "Hiplok", "Joe's No Flats", "Leatt", "Minoura", "Mistral", "SIGG",
    "Time Sport", "UNIOR", "Weldtite", "Camelback", "Altura", "Giro"
]

ZYRO_REMOVE_CATEGORIES = [
    "Bags and Baskets", "BIKES", "Bottle Cages", "Bottles", "Car Racks",
    "Child Seats", "Child Transport Trailers", "Cleaners & Degreasers",
    "Cleaning Tools", "Clothing", "Cycling Computers and GPS",
    "Energy & Recovery Food & Drink", "Goggles", "Helmets", "Hydration Systems",
    "Lubes & Grease", "Map Holders", "Mirrors", "Phone & Accessory Mounts",
    "POS", "PROTECTION", "Pumps and CO2", "Puncture Protection",
    "Puncture Repair", "Racks", "Reflectors", "Shoes", "Sunglasses",
    "Toe Clips and Straps", "Tools", "Trainers and Rollers",
    "Travel/Storage Solutions", "Value Packs", "Workstands"
]

ZYRO_DROP_COLUMNS = [
    "VATNotes", "StockIndicator", "StockDueIn", "BriefDescription",
    "LongDescription", "ImageUrl", "OrangePrice", "BronzePrice", "SilverPrice", "Currency", "BoxQuantity", "CurrencyCode",
]

def clean_zyrofisher(info_df, price_df):
    """
    Cleans Zyrofisher supplier data. Info and Price files are matched on
    Info.SKU -> Price.ProductCode, then rules are applied in order:
    brand filter, category filter, box-quantity removal, column removal.
    Both barcode columns are kept for now.
    Returns: (cleaned_df, removed_df, stats)
    """
    info_df = clean_column_names(info_df)
    price_df = clean_column_names(price_df)
    info_df = info_df.fillna('')
    price_df = price_df.fillna('')

    stats = {'info_file_rows': len(info_df), 'cost_file_rows': len(price_df)}

    def get_col(frame, *names):
        for name in names:
            matches = [c for c in frame.columns if c.lower().replace(' ', '') == name.lower().replace(' ', '')]
            if matches:
                return matches[0]
        return None

    # 1. Merge: Info.SKU -> Price.ProductCode
    sku_col = get_col(info_df, 'SKU')
    product_code_col = get_col(price_df, 'ProductCode')

    if sku_col and product_code_col:
        price_subset = price_df.rename(columns={product_code_col: sku_col})
        df = pd.merge(info_df, price_subset, on=sku_col, how='left', suffixes=('', ' (Price)'))
        matched_mask = info_df[sku_col].isin(price_df[product_code_col])
        stats['matched_with_price'] = int(matched_mask.sum())
    else:
        df = info_df.copy()
        stats['matched_with_price'] = 0
        print("Warning: Could not find SKU/ProductCode columns to merge Zyrofisher files.")

    df = df.fillna('')

    removal_mask = pd.Series(False, index=df.index)
    removal_reason = pd.Series('', index=df.index)

    def add_removals(mask, reason):
        new = mask & ~removal_mask
        removal_reason[new] = reason
        return removal_mask | mask

    # 2. Brand filter (exact match)
    brand_col = get_col(df, 'Brand')
    if brand_col:
        brands = df[brand_col].astype(str).str.strip().str.lower()
        removal_mask = add_removals(brands.isin([b.lower() for b in ZYRO_REMOVE_BRANDS]), 'Brand removed')

    # 3. Category filter (exact match)
    cat_col = get_col(df, 'Category')
    if cat_col:
        cats = df[cat_col].astype(str).str.strip().str.lower()
        removal_mask = add_removals(cats.isin([c.lower() for c in ZYRO_REMOVE_CATEGORIES]), 'Category removed')

    # 4. Box quantity: remove records that have a value
    box_col = get_col(df, 'BoxQuantity', 'Box Qty')
    if box_col:
        has_box_qty = df[box_col].astype(str).str.strip() != ''
        removal_mask = add_removals(has_box_qty, 'Has box quantity')

    all_removed = df[removal_mask].copy()
    all_removed['Removal Reason'] = removal_reason[removal_mask]
    df = df[~removal_mask].copy()

    # 5. Column removal
    cols_to_drop = [c for c in df.columns if c.strip() in ZYRO_DROP_COLUMNS]
    df = df.drop(columns=cols_to_drop)

    stats['removed_rows'] = len(all_removed)
    stats['dropped_columns'] = cols_to_drop

    df['Supplier'] = 'Zyrofisher'
    all_removed['Supplier'] = 'Zyrofisher (Removed)'

    return df, all_removed, stats


# ===== COMMENTED OUT - NOT IN USE =====
# def clean_extra_uk(df):
#     """
#     Cleans Extra UK supplier data according to updated rules.
#     """
#     pass
#
# def standardize_schema(df, supplier_name):
#     """
#     Standardize the cleaned supplier dataframe into the final 19-column Lightspeed schema.
#     """
#     pass
#
# def apply_cross_supplier_rules(chicken_df, extra_df, zyro_df, ison_df):
#     """
#     Merges all supplier dataframes and applies cross-supplier sourcing constraints.
#     """
#     pass
#
# def process_lightspeed_match(allowed_df, banned_df, ls_df):
#     """
#     Compares cleaned items against the Lightspeed extract.
#     """
#     pass
