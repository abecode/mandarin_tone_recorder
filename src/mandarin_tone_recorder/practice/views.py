"""Views for Mandarin practice workflows."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def landing(request: HttpRequest) -> HttpResponse:
    """Render the practice landing page."""
    return render(request, "practice/landing.html")
