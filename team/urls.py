from django.urls import path
from . import views

app_name = 'team'

urlpatterns = [
    # Employee CRUD
    path('',                                      views.employee_list,              name='employee_list'),
    path('add/',                                  views.employee_create,            name='employee_create'),
    path('<int:pk>/',                             views.employee_detail,            name='employee_detail'),
    path('<int:pk>/edit/',                        views.employee_edit,              name='employee_edit'),
    path('<int:pk>/toggle-status/',               views.employee_toggle_status,     name='employee_toggle_status'),

    # Employee Account & Credentials
    path('<int:pk>/password-reset/',              views.employee_password_reset,    name='employee_password_reset'),
    path('<int:pk>/link-account/',                views.employee_link_account,      name='employee_link_account'),

    # Permissions
    path('<int:pk>/permissions/',                 views.employee_permissions,       name='employee_permissions'),
    path('<int:pk>/permissions/reset/',           views.employee_reset_permissions, name='employee_reset_permissions'),

    # Branch access
    path('<int:pk>/branches/',                    views.employee_branches,          name='employee_branches'),

    # Roles & Permissions Management
    path('roles/',                                views.role_list,                  name='role_list'),
    path('roles/add/',                            views.role_create,                name='role_create'),
    path('roles/<int:pk>/edit/',                  views.role_edit,                  name='role_edit'),

    # HR Foundation: Documents
    path('<int:pk>/documents/upload/',            views.employee_document_upload,   name='employee_document_upload'),
    path('<int:pk>/documents/<int:doc_pk>/delete/', views.employee_document_delete,  name='employee_document_delete'),

    # Branches (standalone management)
    path('branches/',                             views.branch_list,                name='branch_list'),
    path('branches/add/',                         views.branch_create,              name='branch_create'),
    path('branches/<int:pk>/edit/',               views.branch_edit,                name='branch_edit'),
]
