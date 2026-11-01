from .models import InAppNotification


def notification_summary(request):
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0}
    return {
        'unread_notification_count': InAppNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }
