import { ApiRoutes } from "../routes";
import { PostTemplateForm, UpdateTemplateForm, Template } from "./models";

export async function FetchTemplates(asc: boolean = false, limit?: number, last_id?: number): Promise<Template[]> {
    let url = ApiRoutes.AllTemplates();
    let templates: Template[] = [];

    // query params
    if (asc) {
        url += "?sort_by=asc&";
    } else {
        url += "?sort_by=desc&";
    }
    if (limit) {
        url += `limit=${limit}&`;
    }
    if (last_id) {
        url += `last_id=${last_id}&`;
    }

    try {
        // TODO: query params
        const response = await fetch(url);
        const body = await response.json();

        body.templates.forEach((t: Template) => {
            templates.push(new Template(t.id, t.title, t.url_tmp ?? '', t.status, t.is_accepted, t.proto_python_lib ?? ''));
        });
    } catch (error: any) {
        console.error(error.message);
    };
    return templates;
}

// TODO: error handling
export async function DeleteTemplate(id: number): Promise<boolean> {
    const url = ApiRoutes.DeleteTemplate(id);
    try {
        const response = await fetch(url, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            credentials: "include",
        });
        const body = await response.json();

        return body.success;

    } catch (error: any) {
        console.error(error.message);
        return false;
    };
}

	
// Response body
// {
//   "success": true,
//   "message": "Шаблон создан",
//   "template_id": 10
// }
export async function CreateTemplate(t: PostTemplateForm): Promise<boolean> {
    const url = ApiRoutes.CreateTemplate();
    try {
        const response = await fetch(url, {
            method: "POST",
            body: JSON.stringify(t),
            headers: { "Content-Type": "application/json" },
            credentials: "include",
        });
        const body = await response.json();

        return body.success;
    } catch (error: any) {
        console.error(error.message);
        return false;
    };
}

export async function UpdateTemplate(t: UpdateTemplateForm): Promise<boolean> {
    const url = ApiRoutes.UpdateTemplate();
    try {
        const response = await fetch(url, {
            method: "PUT",
            body: JSON.stringify(t),
            headers: { "Content-Type": "application/json" },
            credentials: "include",
        });
        const body = await response.json();

        return body.success;
    } catch (error: any) {
        console.error(error.message);
        return false;
    };
}
