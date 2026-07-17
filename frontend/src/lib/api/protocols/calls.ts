import { ApiRoutes } from "../routes";
import { PostProtocolForm, Protocol } from "./models";

export async function FetchProtocols(tmp_id?: number, limit?: number, offset?: number): Promise<Protocol[]> {
    let url = ApiRoutes.AllProtocols() + "?";
    let protocols: Protocol[] = [];

    // query params
    if (tmp_id) {
        url += `tmp_id=${tmp_id}&`;
    };
    if (limit) {
        url += `limit=${limit}&`;
    };
    if (offset) {
        url += `offset=${offset}&`;
    };

    try {
    } catch (error: any) {
    };

    try {
        // TODO: query params
        const response = await fetch(url);
        const body = await response.json();

        body.protocols.forEach((p: Protocol) => {
            protocols.push(new Protocol(p.proto_id, p.name, p.created_at, p.tmp_id, p.tmp_name));
        });
    } catch (error: any) {
        console.error(error.message);
    };
    return protocols;
}

export async function DeleteProtocol(id: number): Promise<boolean> {
    const url = ApiRoutes.DeleteProtocol(id);
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
    }
}

export async function CreateProtocol(form: PostProtocolForm): Promise<boolean> {
    const url = ApiRoutes.CreateProtocol();
    try {
        const response = await fetch(url, {
            method: "POST",
            body: JSON.stringify(form),
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
