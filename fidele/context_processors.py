from fidele.models import Department, Familles


def departement_processor(request):
    departement = Department.objects.all()
    famille = Familles.objects.all()

    context_data = {
        'department': departement,
        'famille': famille,
    }

    return context_data




# def employes_processor(request):
#     employee = Employee.objects.all()
#     documentype = DocumentType.objects.all()
#     docn = EmployeeDocuments.objects.filter(employee=request.user.id).count
#     managerdept = EmployeeDepartment.objects.all()
#     noteservice = NoteService.objects.all()
#
#     current_date = datetime.date.today()
#     leave_employees = Leave.objects.filter(start_date__lte=current_date, end_date__gte=current_date).order_by('-submission_date')[:3]
#     permission_employees = PermissionLeave.objects.filter(start_date__lte=current_date, end_date__gte=current_date).order_by('-submission_date')[:3]
#
#     # user = get_object_or_404(User, pk=pk )
#     # conge = Leave.objects.filter(balance__isnull=False).aggregate(Sum('balance'))
#     conge = Leave.objects.filter(balance__isnull=False, employee__user__id=request.user.id).aggregate(Sum('balance'))
#     conge['balance'] = (conge['balance__sum'])
#     notifications = Notification.objects.filter(recipient=request.user.id)
#     return {'employes': employee, 'leave': conge, 'doc': documentype, 'notifications': notifications, 'number': docn,
#             'manager': managerdept, 'absentconge': leave_employees,'noteservice':noteservice, 'absentpermission': permission_employees,
#             'balance': conge['balance']}


# def week_number_processor(request):
#     my_date = datetime.date.today()
#     year, week_num, day_of_week = my_date.isocalendar()
#     # print("Week #" + str(week_num))
#     sema = ('#' + str(week_num))
#     # sema = datetime.date(2023, 1, 1).strftime('%U')
#     today = timezone.now()
#     employe = Employee.objects.all()
#     prmierjours = datetime.date.today() - datetime.timedelta(days=today.weekday())
#     # datetime.timedelta(days=datetime.date.today().isoweekday() % 7)
#
#     return {'sema': sema, 'today': today, 'employe': employe, 'semday': prmierjours}


# def patient_hospit(request, pk):
#     patient = get_object_or_404(Patient, pk=pk)
#     context = {}
#     context['count'] = patient.hospitalisation_set.all().count()
#     context['hospitalisations'] = patient.hospitalisation_set.all()
#     # examens.patient_examens_set.all(),
#     return render(request, {'hospit': patient, **context})

# def patient_examens(request, pk):
#     patient = get_object_or_404(Patient, pk=pk)
#     context = {}
#     context['examens'] = patient.examens_set.all()
#     context['count'] = patient.examens_set.all().count()
#     context['hospitalisations'] = patient.hospitalisation_set.all()
#     # examens.patient_examens_set.all(),
#     return render(request, {'exam': patient, **context})


# def working_processor(request, pk):
#     project = get_object_or_404(Project, pk=pk)
#     projecttime = project.task_set.filter(employee=request.user.pk).Sum
#
#     return {'timetotal': projecttime}

#
# def employee_documents_processor(request, pk):
#     employee = get_object_or_404(Employee, pk=pk)
#     documents = employee.employeedocuments_set.filter(employee=request.user.pk)
#     lesdocs = EmployeeDocuments.objects.all()
#
#     return {'documents': documents, lesdocs: 'docks'}
#
#
# def absent_employees(request):
#     current_date = datetime.date.today()
#     leave_employees = Leave.objects.filter(start_date__lte=current_date, end_date__gte=current_date)
#     permission_employees = PermissionLeave.objects.filter(start_date__lte=current_date, end_date__gte=current_date)
#     return {'absentconge': leave_employees, 'absentpermission': permission_employees}
