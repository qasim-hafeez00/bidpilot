SELECT customer_id, MIN(order_date) AS first_order
FROM orders
GROUP BY customer_id;
