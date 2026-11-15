CREATE TABLE events (
  id BIGSERIAL PRIMARY KEY,
  tenant_id UUID NOT NULL,
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON events (tenant_id, created_at);
