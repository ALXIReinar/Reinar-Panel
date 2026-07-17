import { FetchTemplates } from "$lib/api/templates/calls";
import type { PageServerLoad } from "../$types";
import { TEMPLATES_LIMIT_COOKIE, parseLimit } from "$lib/constants";

export const load: PageServerLoad = async (event) => {
    const limit = parseLimit(event.cookies.get(TEMPLATES_LIMIT_COOKIE));
    let templates = await FetchTemplates(false, limit);

    return {
        templates,
        limit,
    };
}
