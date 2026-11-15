# project: price-elasticity (synthetic)
import os, json
from sklearn.linear_model import LinearRegression
model = LinearRegression().fit(np.log(price), np.log(qty))
