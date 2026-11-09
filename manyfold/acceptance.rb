require "rack/mock"
require "tempfile"
require "digest"

TYPE = "application/vnd.manyfold.v0+json"
BASE = "http://localhost"

if ARGV.first == "seed"
  FileUtils.mkdir_p("/tmp/library")
  Library.create!(name: "Native acceptance", path: "/tmp/library", storage_service: "filesystem")
  user = User.create!(username: "acceptance", email: "acceptance@example.invalid", password: "acceptance-fixture-only", approved: true)
  user.add_role(:administrator)
  exit
end

user = User.find_by!(username: "acceptance")
library = Library.first!
app = Doorkeeper::Application.create!(name: "Native acceptance", owner: user, redirect_uri: "urn:ietf:wg:oauth:2.0:oob", scopes: "read write delete")
def token_for(app, scopes)
  Doorkeeper::AccessToken.create!(application: app, scopes: scopes, expires_in: 600).plaintext_token
end
read = token_for(app, "read")
write = token_for(app, "read write")
delete = token_for(app, "delete")
http = Rack::MockRequest.new(Rails.application)

def request(http, token, method, path, body = nil)
  http.request(method, BASE + path, "HTTP_AUTHORIZATION" => "Bearer #{token}", "HTTP_ACCEPT" => TYPE, "CONTENT_TYPE" => (path == "/models/merge" ? "application/json" : TYPE), input: body ? JSON.generate(body) : "")
end

def require_status(response, expected)
  raise "expected #{expected}, got #{response.status}: #{response.body[0, 1000]}" unless response.status == expected
end

def make_model(library, path)
  Model.create!(name: path, library: library, path: path, license: "CC0-1.0")
end

def add_file(model, filename, content)
  file = ModelFile.new(model: model, filename: filename)
  Tempfile.create(["request-stream", ".dat"]) do |stream|
    stream.binmode
    stream.write(content)
    stream.rewind
    File.unlink(stream.path)
    file.attachment_attacher.attach(stream, storage: model.library.storage_key)
    file.save!
  end
  file.update!(digest: Digest::SHA256.hexdigest(content))
  file
end

target = make_model(library, "target")
source = make_model(library, "source")
collection = Collection.create!(name: "Reviewed projects")
existing = add_file(target, "same.stl", "solid native\nendsolid native\n")
duplicate = add_file(source, "same.stl", "solid native\nendsolid native\n")
distinct = add_file(source, "distinct.stl", "solid retained\nendsolid retained\n")
duplicate_path = library.storage.path(duplicate.path_within_library)

raise "canonical filename missing" unless distinct.attachment.original_filename == "distinct.stl"
raise "canonical MIME missing" unless distinct.attachment.mime_type == Mime::Type.lookup_by_extension("stl").to_s
raise "duplicate fixture wasn't stored" unless File.file?(duplicate_path)

payload = {models: [source.public_id], target: target.public_id}
require_status(request(http, read, "POST", "/models/merge", payload), 403)
require_status(request(http, delete, "POST", "/models/merge", payload), 403)
require_status(request(http, write, "DELETE", "/models/#{source.public_id}"), 403)
raise "rejected calls changed source" unless Model.exists?(source.id)

require_status(request(http, write, "PATCH", "/models/#{target.public_id}", {name: target.name, isPartOf: [{"@id" => "#{BASE}/collections/#{collection.public_id}"}]}), 200)
raise "collection reference not assigned" unless target.reload.collections == [collection]

require_status(request(http, write, "POST", "/models/merge", payload), 302)
raise "source model survived merge" if Model.exists?(source.id)
raise "duplicate source survived on disk" if File.exist?(duplicate_path)
raise "distinct file lost" unless target.reload.model_files.exists?(distinct.id)
raise "distinct bytes changed" unless File.binread(library.storage.path(distinct.reload.path_within_library)) == "solid retained\nendsolid retained\n"
raise "target bytes changed" unless File.binread(library.storage.path(existing.reload.path_within_library)) == "solid native\nendsolid native\n"

# A third same-name file must retain both the already-renamed and new content.
first = make_model(library, "collision-one")
second = make_model(library, "collision-two")
a = add_file(first, "same.stl", "solid first\nendsolid first\n")
b = add_file(second, "same.stl", "solid second\nendsolid second\n")
[first, second].each do |model|
  require_status(request(http, write, "POST", "/models/merge", {models: [model.public_id], target: target.public_id}), 302)
end
[a, b].each { |file| raise "colliding file lost" unless target.model_files.exists?(file.id) }
raise "collision overwrote a file" unless target.model_files.pluck(:filename).uniq.length == target.model_files.count
# Nested scans can have two rows pointing at the same physical attachment.
parent = make_model(library, "shared")
child = make_model(library, "shared/child")
shared = add_file(child, "aliased.stl", "solid shared\nendsolid shared\n")
alias_file = ModelFile.create!(model: parent, filename: "child/aliased.stl", attachment_data: shared.attachment_data, digest: shared.digest)
shared_path = library.storage.path(shared.path_within_library)
require_status(request(http, write, "POST", "/models/merge", {models: [child.public_id], target: parent.public_id}), 302)
raise "shared bytes removed" unless File.binread(shared_path) == "solid shared\nendsolid shared\n"
raise "shared target row removed" unless parent.reload.model_files.exists?(alias_file.id)
puts "native merge, scope boundaries, collection references, unlinked streams, metadata and collision preservation passed"
