"""Django admin configuration for practice models."""

from django.contrib import admin

from mandarin_tone_recorder.practice.models import (
    PracticeAttempt,
    PracticeDeck,
    PracticeHintEvent,
    PracticeItem,
    PracticeSession,
)
from mandarin_tone_recorder.practice.services import generate_pinyin_text


class PracticeItemInline(admin.TabularInline):
    model = PracticeItem
    extra = 0


@admin.register(PracticeDeck)
class PracticeDeckAdmin(admin.ModelAdmin):
    inlines = (PracticeItemInline,)
    fields = (
        "title",
        "slug",
        "version",
        "user",
        "activity_type",
        "response_type",
        "is_shared",
        "is_builtin",
        "source_path",
        "original_pasted_text",
        "created_at",
        "updated_at",
    )
    list_display = ("title", "slug", "version", "user", "is_shared", "is_builtin")
    list_filter = ("is_shared", "is_builtin", "activity_type", "response_type")
    readonly_fields = ("original_pasted_text", "created_at", "updated_at")
    search_fields = ("title", "slug", "source_text", "items__prompt_text")

    @admin.display(description="Original pasted text")
    def original_pasted_text(self, deck: PracticeDeck) -> str:
        return deck.source_text


@admin.register(PracticeItem)
class PracticeItemAdmin(admin.ModelAdmin):
    actions = ("regenerate_pinyin",)
    list_display = ("prompt_text", "pinyin_text", "deck", "sort_order")
    list_filter = ("deck",)
    search_fields = ("prompt_text", "pinyin_text", "deck__title")

    def save_model(self, request, obj, form, change) -> None:
        if not change and not obj.pinyin_text:
            obj.pinyin_text = generate_pinyin_text(obj.prompt_text)
        elif (
            change
            and "prompt_text" in form.changed_data
            and "pinyin_text" not in form.changed_data
        ):
            obj.pinyin_text = generate_pinyin_text(obj.prompt_text)
        super().save_model(request, obj, form, change)

    @admin.action(description="Regenerate pinyin for selected practice items")
    def regenerate_pinyin(self, request, queryset) -> None:
        updated_count = 0
        for item in queryset:
            item.pinyin_text = generate_pinyin_text(item.prompt_text)
            item.save(update_fields=("pinyin_text",))
            updated_count += 1

        self.message_user(
            request,
            f"Regenerated pinyin for {updated_count} practice item(s).",
        )


admin.site.register(PracticeSession)
admin.site.register(PracticeAttempt)
admin.site.register(PracticeHintEvent)
