# project: sagemaker-mlops (synthetic)
import os, json
import mlflow
with mlflow.start_run():
    mlflow.log_params(params)
    model.fit(X_train, y_train)
    mlflow.log_metric('auc', auc)
    mlflow.sklearn.log_model(model, 'model', registered_model_name='churn')
