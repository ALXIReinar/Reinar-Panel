import { ApiRoutes } from "../routes";
import { Seance } from "./models";

export async function Login(login: string, passw: string) {
    const url = ApiRoutes.Login();
    try {
        const response = await fetch(url, {
            method: "POST",
            body: JSON.stringify({ login, passw }),
            headers: { "Content-Type": "application/json" },
        });
        if (!response.ok) {
            throw new Error(`Response status: ${response.status}`);
        }

        const result = await response.json();
        if (result.success === true) {
            return true;
        } else {
            return false;
        }
    } catch (error: any) {
        console.error(error.message);
        return false;
    }
}

export async function Sessions(): Promise<Seance[]> {
    const url = ApiRoutes.AdminSessions();
    let seances: Seance[] = [];
    try {
        const response = await fetch(url, {
            method: "POST",
            credentials: "include",
        });

        if (!response.ok) {
            throw new Error(`Response status: ${response.status}`);
        }

        const result = await response.json();
        console.log(result);

        for (let i = 0; i < result.length; i++) {
            seances.push(new Seance(result[i].user_agent, result[i].ip));
        }
    } catch (error: any) {
        console.error(error.message);
    }
    return seances;
}
