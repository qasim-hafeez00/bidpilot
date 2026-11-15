# project: llm-finetune (synthetic)
import os, json
import torch
from torch import nn

class Head(nn.Module):
    def __init__(self, d):
        super().__init__(); self.fc = nn.Linear(d, 2)
    def forward(self, x):
        return self.fc(x)
