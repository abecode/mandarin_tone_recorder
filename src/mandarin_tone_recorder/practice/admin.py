"""Django admin configuration for practice models."""

from django.contrib import admin

from mandarin_tone_recorder.practice.models import (
    PracticeAttempt,
    PracticeDeck,
    PracticeHintEvent,
    PracticeItem,
    PracticeSession,
)


class PracticeItemInline(admin.TabularInline):
    model = PracticeItem
    extra = 0


@admin.register(PracticeDeck)
class PracticeDeckAdmin(admin.ModelAdmin):
    inlines = (PracticeItemInline,)
    list_display = ("title", "user", "is_shared", "created_at")
    list_filter = ("is_shared", "created_at")
    search_fields = ("title", "source_text", "items__prompt_text")


admin.site.register(PracticeSession)
admin.site.register(PracticeAttempt)
admin.site.register(PracticeHintEvent)
