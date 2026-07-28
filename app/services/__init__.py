"""
Service layer — application orchestration.

This layer exists so the api/ routers stay thin and never import Temporal
workflow classes, repositories, or models directly. It sits between api/ and
the durable-execution / persistence layers.

Layering:
  api/      → calls services/, domain/, schemas/
  services/ → calls workflows/ (dispatch), repositories/, clients/, domain/, schemas/
              owns Temporal-error → AppError translation
  services/ → never imported by domain/ or core/
"""
