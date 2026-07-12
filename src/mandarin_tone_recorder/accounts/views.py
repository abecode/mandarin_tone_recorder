"""Views for account creation and authentication helpers."""

from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from mandarin_tone_recorder.accounts.forms import SignUpForm


@require_http_methods(["GET", "POST"])
def signup(request: HttpRequest) -> HttpResponse:
    """Create an account and sign the user in."""
    form = SignUpForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("home")
    return render(request, "registration/signup.html", {"form": form})
