"""
Test simple de importación CSV
"""
import csv
import io

# Simular las primeras líneas del CSV del usuario
csv_sample = """Time,Symbol,Side,Price,Quantity,Realized Profit,Fee,Order ID
2025-12-19 21:53:02,SOL-USDT,Buy,185.85,0.27,-,-,123456789
2025-12-19 22:10:15,SOL-USDT,Sell,186.50,0.27,0.1755,0.0503,123456790
2026-01-15 14:30:45,BTC-USDT,Buy,42500.00,0.01,-,-,123456791
"""

print("=== Test de parsing CSV ===")
csv_file = io.StringIO(csv_sample)
reader = csv.DictReader(csv_file)

print(f"Headers: {reader.fieldnames}")
print()

for i, row in enumerate(reader):
    print(f"Fila {i+1}:")
    print(f"  Time: '{row.get('Time')}'")
    print(f"  Symbol: '{row.get('Symbol')}'")
    print(f"  Side: '{row.get('Side')}'")
    print(f"  Realized Profit: '{row.get('Realized Profit')}'")
    
    # Verificar si tiene profit
    profit_str = row.get('Realized Profit', '')
    if profit_str and profit_str.strip() not in ['', '-']:
        print(f"  -> TIENE PnL: {profit_str}")
    else:
        print(f"  -> SIN PnL (omitir)")
    print()

print("=== Test completado ===")
