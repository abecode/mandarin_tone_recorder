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
    fields = (
        "title",
        "user",
        "is_shared",
        "original_pasted_text",
        "created_at",
        "updated_at",
    )
    list_display = ("title", "user", "is_shared", "created_at")
    list_filter = ("is_shared", "created_at")
    readonly_fields = ("original_pasted_text", "created_at", "updated_at")
    search_fields = ("title", "source_text", "items__prompt_text")

    @admin.display(description="Original pasted text")
    def original_pasted_text(self, deck: PracticeDeck) -> str:
        return deck.source_text


admin.site.register(PracticeSession)
admin.site.register(PracticeAttempt)
admin.site.register(PracticeHintEvent)
