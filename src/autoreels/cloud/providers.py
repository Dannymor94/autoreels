"""Провайдер-абстракция: Groq → OpenRouter failover. Round-robin, троттлинг по x-ratelimit,
бэкофф по retry-after, prompt-cache на стабильный system-промпт.
"""
