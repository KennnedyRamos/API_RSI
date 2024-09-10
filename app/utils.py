import numpy as np

def calcular_rsi(closes, periodo):
    diffs = np.diff(closes)
    ganhos = np.where(diffs > 0, diffs, 0)
    perdas = np.where(diffs < 0, -diffs, 0)
    
    media_ganhos = np.mean(ganhos[:periodo])
    media_perdas = np.mean(perdas[:periodo])
    

    if media_perdas == 0:
        rsi = 100.0 
    else:
        rs = media_ganhos / media_perdas
        rsi = 100 - (100 / (1 + rs))
    
    return round(float(rsi), 2)
