"""
routes/tasks.py

Módulo para criação e gerenciamento de tarefas para os técnicos.
"""
from flask import (Blueprint, render_template, request, redirect, url_for, flash, abort)
from flask_login import login_required, current_user
from sqlalchemy import desc

from models import Task, TaskAssignment, User, Notification
from extensions import db
from .utils import admin_required, notify_admins

tasks_bp = Blueprint('tasks', __name__, template_folder='templates')


@tasks_bp.route('/tasks')
@login_required
def technician_tasks():
    """Visão do técnico de suas tarefas atribuídas."""
    assignments = TaskAssignment.query.join(Task).filter(
        TaskAssignment.user_id == current_user.id
    ).order_by(desc(Task.created_date)).all()
    return render_template('technician_tasks.html', assignments=assignments)


@tasks_bp.route('/tasks/admin')
@login_required
@admin_required
def admin_tasks():
    """Visão do administrador de todas as tarefas criadas."""
    tasks = Task.query.order_by(desc(Task.created_date)).all()
    return render_template('admin_tasks.html', tasks=tasks)


@tasks_bp.route('/tasks/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create_task():
    """Cria uma nova tarefa e a atribui a técnicos."""
    technicians = User.query.filter_by(role='technician').order_by(User.username).all()
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        technician_ids = request.form.getlist('technician_ids')
        if not title or not technician_ids:
            flash('Título e ao menos um técnico são obrigatórios.', 'danger')
            return render_template('task_form.html', technicians=technicians, task=None)
        try:
            new_task = Task(title=title, description=description, creator_id=current_user.id)
            db.session.add(new_task)
            db.session.flush()
            for tech_id in technician_ids:
                assignment = TaskAssignment(task_id=new_task.id, user_id=int(tech_id))
                db.session.add(assignment)
                # Notificar técnico sobre nova tarefa
                notif_msg = f"Uma nova tarefa '{title}' foi atribuída a você."
                notif = Notification(user_id=int(tech_id), message=notif_msg, url=url_for('tasks.technician_tasks'))
                db.session.add(notif)

            db.session.commit()
            flash('Tarefa criada e atribuída com sucesso!', 'success')
            return redirect(url_for('tasks.admin_tasks'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao criar tarefa: {e}', 'danger')
    return render_template('task_form.html', technicians=technicians, task=None)


@tasks_bp.route('/tasks/edit/<int:task_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_task(task_id):
    """Edita uma tarefa existente."""
    task = db.session.get(Task, task_id)
    if not task:
        abort(404)
    technicians = User.query.filter_by(role='technician').order_by(User.username).all()
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        new_technician_ids = {int(i) for i in request.form.getlist('technician_ids')}
        if not title or not new_technician_ids:
            flash('Título e ao menos um técnico são obrigatórios.', 'danger')
            return render_template('task_form.html', technicians=technicians, task=task)
        try:
            task.title = title
            task.description = description
            current_technician_ids = {a.user_id for a in task.assignments}
            
            ids_to_remove = current_technician_ids - new_technician_ids
            if ids_to_remove:
                TaskAssignment.query.filter(TaskAssignment.task_id == task_id, TaskAssignment.user_id.in_(ids_to_remove)).delete(synchronize_session=False)

            ids_to_add = new_technician_ids - current_technician_ids
            for tech_id in ids_to_add:
                new_assignment = TaskAssignment(task_id=task_id, user_id=tech_id)
                db.session.add(new_assignment)

            # Notificar todos os técnicos (novos e antigos) sobre a atualização
            admin_msg = f"Tarefa '{task.title}' foi atualizada por {current_user.username}."
            notify_admins(admin_msg, url_for('tasks.admin_tasks'), excluded_user_id=current_user.id)
            
            for tech_id in new_technician_ids:
                tech_msg = f"A tarefa '{task.title}' atribuída a você foi atualizada."
                notif = Notification(user_id=tech_id, message=tech_msg, url=url_for('tasks.technician_tasks'))
                db.session.add(notif)

            db.session.commit()
            flash('Tarefa atualizada com sucesso!', 'success')
            return redirect(url_for('tasks.admin_tasks'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao atualizar tarefa: {e}', 'danger')
    assigned_technician_ids = [a.user_id for a in task.assignments]
    return render_template('task_form.html', title="Editar Tarefa", task=task, technicians=technicians, assigned_technician_ids=assigned_technician_ids)


@tasks_bp.route('/tasks/delete/<int:task_id>', methods=['POST'])
@login_required
@admin_required
def delete_task(task_id):
    """Exclui uma tarefa."""
    task = db.session.get(Task, task_id)
    if not task:
        abort(404)
    try:
        # Notificar admins e técnicos antes de deletar
        admin_msg = f"A tarefa '{task.title}' foi deletada por {current_user.username}."
        notify_admins(admin_msg, url_for('tasks.admin_tasks'), excluded_user_id=current_user.id)
        
        for assignment in task.assignments:
            tech_msg = f"A tarefa '{task.title}' que estava atribuída a você foi deletada."
            notif = Notification(user_id=assignment.user_id, message=tech_msg, url=url_for('tasks.technician_tasks'))
            db.session.add(notif)

        db.session.delete(task)
        db.session.commit()
        flash('Tarefa deletada com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao deletar tarefa: {e}', 'danger')
    return redirect(url_for('tasks.admin_tasks'))


@tasks_bp.route('/tasks/update_status/<int:assignment_id>', methods=['POST'])
@login_required
def update_task_status(assignment_id):
    """Atualiza o status de uma tarefa atribuída (visão do técnico)."""
    assignment = db.session.get(TaskAssignment, assignment_id)
    if not assignment:
        abort(404)
    if assignment.user_id != current_user.id and current_user.role != 'admin':
        abort(403)
    try:
        new_status = request.form.get('status')
        observation = request.form.get('observation')
        assignment.status = new_status
        assignment.observation = observation
        db.session.commit()

        creator_id = assignment.task.creator_id
        if creator_id != current_user.id:
            admin_msg = f"O técnico {current_user.username} atualizou a tarefa '{assignment.task.title}' para '{new_status}'."
            admin_notif = Notification(user_id=creator_id, message=admin_msg, url=url_for('tasks.admin_tasks'))
            db.session.add(admin_notif)
            db.session.commit()

        flash('Status da tarefa atualizado.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao atualizar status: {e}', 'danger')

    return redirect(url_for('tasks.technician_tasks'))