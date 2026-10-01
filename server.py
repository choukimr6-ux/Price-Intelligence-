"""
Algeria Furniture Hardware Price Intelligence MCP Server
Author: Hardware Intelligence Team
License: MIT
"""

import os
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
import numpy as np
from mcp.server.fastmcp import FastMCP

# تهيئة خادم MCP
mcp = FastMCP("Algeria Furniture Hardware Intelligence")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_intelligence.db")


def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول إذا لم تكن موجودة."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. الكتالوج المرجعي للمنتجات (Product Master)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_master (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_sku TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,
        subcategory TEXT NOT NULL,
        opening_angle TEXT,
        overlay_type TEXT,
        closing_mechanism TEXT,
        specs_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. الموردين والمستوردين (Suppliers & Competitors)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        supplier_type TEXT, -- Importer, Wholesaler, Retailer, Manufacturer
        wilaya TEXT NOT NULL,
        city TEXT,
        phone TEXT,
        whatsapp TEXT,
        facebook_url TEXT,
        trust_rating INTEGER DEFAULT 3, -- 1 to 5
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. ملاحظات الأسعار الميدانية (Price Observations)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        supplier_id INTEGER NOT NULL,
        brand TEXT NOT NULL,
        brand_tier TEXT DEFAULT 'Generic', -- Generic, Mid-tier, Premium
        price_da REAL NOT NULL,
        tax_status TEXT DEFAULT 'TTC', -- HT or TTC
        quantity_tier TEXT NOT NULL, -- 1-10, 11-50, 51-100, 101-500, 501-1000, 1000+
        actual_quantity INTEGER,
        payment_terms TEXT DEFAULT 'Cash', -- Cash, Chèque, Facilitated
        delivery_included INTEGER DEFAULT 0, -- 1 for True, 0 for False
        evidence_level TEXT NOT NULL, -- Tier 1 (Invoice/Proforma), Tier 2 (Direct Quote/WhatsApp), Tier 3 (Web/Social)
        source_reference TEXT,
        observation_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES product_master(id),
        FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
    );
    """)

    seed_products = [
        ("HINGE-110-FO-SOFT", "Hinges", "Concealed Hinges", "110", "Full Overlay", "Soft Close", '{"cup_diameter": 35}'),
        ("HINGE-110-HO-SOFT", "Hinges", "Concealed Hinges", "110", "Half Overlay", "Soft Close", '{"cup_diameter": 35}'),
        ("HINGE-110-IN-SOFT", "Hinges", "Concealed Hinges", "110", "Inset", "Soft Close", '{"cup_diameter": 35}'),
        ("HINGE-165-FO-SOFT", "Hinges", "Concealed Hinges", "165", "Full Overlay", "Soft Close", '{"cup_diameter": 35}'),
        ("RUNNER-SLIM-450-SOFT", "Drawer Runners", "Slim Drawer Box", None, None, "Soft Close", '{"length_mm": 450, "load_kg": 35}'),
        ("RUNNER-BALL-450-SOFT", "Drawer Runners", "Telescopic Ball Bearing", None, None, "Soft Close", '{"length_mm": 450, "load_kg": 45}')
    ]

    for p in seed_products:
        cursor.execute("""
        INSERT OR IGNORE INTO product_master (canonical_sku, category, subcategory, opening_angle, overlay_type, closing_mechanism, specs_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, p)

    conn.commit()
    conn.close()


init_db()


@mcp.tool()
def add_supplier(
    name: str,
    wilaya: str,
    supplier_type: str = "Wholesaler",
    city: Optional[str] = None,
    phone: Optional[str] = None,
    whatsapp: Optional[str] = None,
    facebook_url: Optional[str] = None,
    trust_rating: int = 3,
    notes: Optional[str] = None
) -> str:
    """إضافة مورد جديد أو مستورد لقاعدة البيانات."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO suppliers (name, supplier_type, wilaya, city, phone, whatsapp, facebook_url, trust_rating, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, supplier_type, wilaya, city, phone, whatsapp, facebook_url, trust_rating, notes))
        conn.commit()
        return f"تم تسجيل المورد '{name}' بنجاح بالمعرف (ID: {cursor.lastrowid})."
    except sqlite3.IntegrityError:
        return f"خطأ: المورد '{name}' مسجل بالفعل."
    finally:
        conn.close()


@mcp.tool()
def log_price_observation(
    canonical_sku: str,
    supplier_name: str,
    brand: str,
    price_da: float,
    quantity_tier: str,
    evidence_level: str,
    brand_tier: str = "Generic",
    actual_quantity: Optional[int] = None,
    tax_status: str = "TTC",
    payment_terms: str = "Cash",
    delivery_included: bool = False,
    source_reference: Optional[str] = None,
    observation_date: Optional[str] = None
) -> str:
    """تسجيل ملاحظة سعر فعلية من السوق (فاتورة، عرض أسعار، استقصاء ميداني)."""
    if not observation_date:
        observation_date = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM product_master WHERE canonical_sku = ?", (canonical_sku,))
    p_row = cursor.fetchone()
    if not p_row:
        conn.close()
        return f"خطأ: المنتج '{canonical_sku}' غير موجود في Product Master."
    product_id = p_row[0]

    cursor.execute("SELECT id FROM suppliers WHERE name = ?", (supplier_name,))
    s_row = cursor.fetchone()
    if not s_row:
        conn.close()
        return f"خطأ: المورد '{supplier_name}' غير موجود. يرجى إضافته أولاً عبر add_supplier."
    supplier_id = s_row[0]

    cursor.execute("""
    INSERT INTO price_observations (
        product_id, supplier_id, brand, brand_tier, price_da, tax_status, 
        quantity_tier, actual_quantity, payment_terms, delivery_included, 
        evidence_level, source_reference, observation_date
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        product_id, supplier_id, brand, brand_tier, price_da, tax_status,
        quantity_tier, actual_quantity, payment_terms, 1 if delivery_included else 0,
        evidence_level, source_reference, observation_date
    ))

    conn.commit()
    obs_id = cursor.lastrowid
    conn.close()

    return f"تم تسجيل ملاحظة السعر بنجاح (ID: {obs_id}): {price_da} DA للمنتج {canonical_sku} من المورد {supplier_name} ({quantity_tier})."


@mcp.tool()
def benchmark_price(
    canonical_sku: str,
    quantity_tier: Optional[str] = None,
    brand_tier: Optional[str] = None,
    wilaya: Optional[str] = None
) -> Dict[str, Any]:
    """حساب الـ Benchmark الإحصائي لسعر منتج معين بدقة: Min, P25, Median, P75, Max."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    query = """
    SELECT po.price_da, po.brand, po.evidence_level, po.observation_date, s.name, s.wilaya
    FROM price_observations po
    JOIN product_master pm ON po.product_id = pm.id
    JOIN suppliers s ON po.supplier_id = s.id
    WHERE pm.canonical_sku = ?
    """
    params: List[Any] = [canonical_sku]

    if quantity_tier:
        query += " AND po.quantity_tier = ?"
        params.append(quantity_tier)
    if brand_tier:
        query += " AND po.brand_tier = ?"
        params.append(brand_tier)
    if wilaya:
        query += " AND s.wilaya = ?"
        params.append(wilaya)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "status": "No data found",
            "message": f"لا توجد ملاحظات أسعار مسجلة للمنتج {canonical_sku} بالمعايير المحددة."
        }

    prices = [r[0] for r in rows]
    prices_arr = np.array(prices)

    min_p = float(np.min(prices_arr))
    p25 = float(np.percentile(prices_arr, 25))
    median = float(np.median(prices_arr))
    p75 = float(np.percentile(prices_arr, 75))
    max_p = float(np.max(prices_arr))

    samples = [
        {
            "price_da": r[0],
            "brand": r[1],
            "evidence": r[2],
            "date": r[3],
            "supplier": r[4],
            "wilaya": r[5]
        }
        for r in rows
    ]

    return {
        "sku": canonical_sku,
        "sample_count": len(prices),
        "benchmark_summary_da": {
            "min": round(min_p, 2),
            "p25": round(p25, 2),
            "median": round(median, 2),
            "p75": round(p75, 2),
            "max": round(max_p, 2)
        },
        "filters_applied": {
            "quantity_tier": quantity_tier,
            "brand_tier": brand_tier,
            "wilaya": wilaya
        },
        "recent_observations": samples[:10]
    }


@mcp.tool()
def list_products(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """استرجاع قائمة المنتجات المعتمدة في Product Master."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if category:
        cursor.execute("SELECT canonical_sku, category, subcategory, opening_angle, overlay_type, closing_mechanism FROM product_master WHERE category = ?", (category,))
    else:
        cursor.execute("SELECT canonical_sku, category, subcategory, opening_angle, overlay_type, closing_mechanism FROM product_master")
    
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "canonical_sku": r[0],
            "category": r[1],
            "subcategory": r[2],
            "angle": r[3],
            "overlay": r[4],
            "closing": r[5]
        }
        for r in rows
    ]


@mcp.tool()
def get_supplier_profile(supplier_name: str) -> Dict[str, Any]:
    """استخراج ملف استخبارات كامل عن مورد معين وأسعاره وتاريخ نشاطه."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, supplier_type, wilaya, city, phone, whatsapp, trust_rating FROM suppliers WHERE name = ?", (supplier_name,))
    s_row = cursor.fetchone()
    if not s_row:
        conn.close()
        return {"error": f"المورد '{supplier_name}' غير موجود."}

    s_id = s_row[0]
    cursor.execute("""
    SELECT pm.canonical_sku, po.brand, po.price_da, po.quantity_tier, po.observation_date, po.evidence_level
    FROM price_observations po
    JOIN product_master pm ON po.product_id = pm.id
    WHERE po.supplier_id = ?
    ORDER BY po.observation_date DESC
    """, (s_id,))
    history = cursor.fetchall()
    conn.close()

    return {
        "supplier_details": {
            "name": s_row[1],
            "type": s_row[2],
            "wilaya": s_row[3],
            "city": s_row[4],
            "phone": s_row[5],
            "whatsapp": s_row[6],
            "trust_rating": s_row[7]
        },
        "total_quoted_products": len(history),
        "recent_quotes": [
            {
                "sku": h[0],
                "brand": h[1],
                "price_da": h[2],
                "tier": h[3],
                "date": h[4],
                "evidence": h[5]
            }
            for h in history
        ]
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
