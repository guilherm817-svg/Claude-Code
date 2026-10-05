"""Webhooks de exemplo, no formato que cada plataforma envia."""

import copy


def hotmart(evento="PURCHASE_APPROVED", transacao="HP1234567890", sck=None, tipo="PIX", preco=197.0):
    return copy.deepcopy({
        "id": "8b8e3a0c-0000-4000-8000-000000000001",
        "creation_date": 1759683600000,
        "event": evento,
        "version": "2.0.0",
        "data": {
            "product": {"id": 3712345, "ucode": "abc", "name": "Curso de Tráfego"},
            "buyer": {"email": "Cliente@Exemplo.com", "name": "Maria da Silva", "checkout_phone": "11999998888",
                      "document": "123.456.789-00"},
            "commissions": [
                {"value": 19.5, "source": "MARKETPLACE", "currency_value": "BRL"},
                {"value": 177.5, "source": "PRODUCER", "currency_value": "BRL"},
            ],
            "purchase": {
                "approved_date": 1759683700000,
                "full_price": {"value": preco, "currency_value": "BRL"},
                "price": {"value": preco, "currency_value": "BRL"},
                "order_date": 1759683600000,  # 2025-10-05 14:00 em São Paulo
                "status": "APPROVED",
                "transaction": transacao,
                "payment": {"installments_number": 1, "type": tipo},
                "origin": {"sck": sck, "src": None, "xcod": None},
            },
        },
    })


def kiwify(status="paid", evento="order_approved", pedido="kw-0001", metodo="credit_card", tracking=None):
    return copy.deepcopy({
        "order_id": pedido,
        "order_ref": "ABC123",
        "order_status": status,
        "webhook_event_type": evento,
        "payment_method": metodo,
        "created_at": "2025-10-05 10:15",
        "updated_at": "2025-10-05 10:16",
        "approved_date": "2025-10-05 10:16" if status == "paid" else None,
        "Product": {"product_id": "prod-kw-1", "product_name": "Mentoria Kiwify"},
        "Customer": {"full_name": "João Souza", "email": "joao@exemplo.com", "mobile": "+5521988887777",
                     "CPF": "98765432100", "ip": "200.100.50.25"},
        "Commissions": {"charge_amount": 9700, "product_base_price": 9700, "kiwify_fee": 897,
                        "settlement_amount": 8803, "my_commission": 8803, "currency": "BRL"},
        "TrackingParameters": tracking or {"src": None, "sck": None, "utm_source": None, "utm_medium": None,
                                           "utm_campaign": None, "utm_content": None, "utm_term": None},
    })
