# project: python-cleaning (synthetic)
import os, json
import numpy as np
weights = np.asarray(w) / np.sum(w)
mean = np.average(x, weights=weights)
