"""Project-level page views."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    """Render the initial authenticated application shell."""
    return render(request, "home.html")
