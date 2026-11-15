# project: sentiment-dash (synthetic)
import os, json
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.bar(summary.index, summary.values)
fig.savefig('report.png', dpi=150)
