"""smoke 용 iris CSV 생성. label 컬럼을 명시적으로 추가."""
import pandas as pd
from sklearn.datasets import load_iris

iris = load_iris(as_frame=True)
df = iris.frame.rename(columns={"target": "label"})
df.columns = [c.replace(" (cm)", "").replace(" ", "_") for c in df.columns]
df.to_csv("iris.csv", index=False)
print(f"wrote iris.csv n={len(df)}")
