# apps/care/permissions.py
from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsReporterOrStaffSameChurch(BasePermission):
    """
    - Un fidèle ne voit que ses propres signalements.
    - Staff avec perm 'can_view_all_problems' voit ceux de son église.
    - Assigné peut voir/éditer le signalement.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False

        # Propriétaire (reporter)
        if hasattr(user, "fidele") and obj.reporter_id == user.fidele.id:
            return True

        # Assigné
        if obj.assignee_id == user.id:
            return True

        # Staff de la même église avec permission
        if user.has_perm("care.can_view_all_problems"):
            try:
                return user.fidele.eglise_id == obj.eglise_id or user.employee.eglise_id == obj.eglise_id
            except Exception:
                return False

        # Lecture publique très limitée (désactivée par défaut)
        return False