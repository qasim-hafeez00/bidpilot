{{ config(materialized='incremental', unique_key='invoice_id') }}
select * from {{ ref('stg_invoices') }}
{% if is_incremental() %} where updated_at > (select max(updated_at) from {{ this }}) {% endif %}
